# Security Research Report — TSAR Trading Super Agent

**Score: 6.5/10**
**Reviewer:** Security Research Council
**Date:** 2026-08-01
**Scope:** Full codebase + external threat landscape (August 2026)
**Prior Baseline:** CP1 Security Review (5.5/10) — July 2026

---

## Executive Summary

TSAR's security posture has **improved from 5.5 to 6.5** since the July 2026 CP1 review, driven by the Security Hardening team's fixes to all 5 critical/high findings (API auth, CORS, Telegram bot auth, LLM injection, weak secrets). The codebase now has solid **defensive foundations** — Bearer token auth, input sanitization, fail-safe kill switch, parameterized SQL, and non-root Docker. However, the August 2026 threat landscape introduces **new attack vectors** that the current defenses don't fully address, particularly around AI agent security, MEV protection, and infrastructure hardening for live trading.

**The system is safe for paper trading. It is NOT safe for live trading with real funds without the Phase 1-2 remediations below.**

---

## 1. Threat Landscape (August 2026)

### 1.1 AI Agent Security — The Dominant Threat

The August 2026 threat landscape is dominated by **AI agent attack vectors** that didn't exist 12 months ago:

- **TradeTrap (arXiv 2512.02261, Dec 2025):** Demonstrated that LLM-based trading agents are vulnerable to adversarial prompt injection through market data feeds. Attackers embed instructions in trade theses, news headlines, and order book data that manipulate LLM decision-making.

- **AI Agents in Cryptoland (arXiv 2503.16248, Mar 2025):** Showed practical prompt injection attacks where malicious replies embedded in on-chain data caused LLM agents to execute unauthorized Ethereum transfers. Directly applicable to TSAR's trade_philosopher and signal_scout agents.

- **IBM Agentic AI Vulnerabilities Report (Aug 2025):** Found 43% of agentic AI attacks are prompt injection, 28% memory poisoning, 19% tool misuse, 10% privilege escalation. TSAR's multi-agent architecture with shared knowledge stores (SQLite, ChromaDB, Redis) creates a wide attack surface for all four categories.

- **OWASP LLM Top 10 (2025):** LLM01 (Prompt Injection), LLM02 (Sensitive Information Disclosure), and LLM05 (Supply Chain Vulnerabilities) are directly relevant to TSAR's LLM-integrated trading pipeline.

### 1.2 MEV and Front-Running

- **MEV Formalization (ScienceDirect, Mar 2026):** Comprehensive formalization of MEV attack strategies including front-running, back-running, sandwich, and suppression attacks. TSAR's centralized exchange (CEX) model avoids on-chain MEV but remains vulnerable to **exchange-level front-running** through order flow prediction.

- **MEV-Boost Relay Exploits (Feb 2026):** Demonstrated that even MEV protection infrastructure can be exploited through bait transactions. Relevant if TSAR ever moves to DEX trading.

### 1.3 DeFi Oracle Manipulation

- **OWASP Smart Contract Top 10 (2026):** SC03 is now "Price Oracle Manipulation" — elevated from previous years. Flash loan-facilitated oracle attacks remain the #1 DeFi exploit vector.

- **Event-Enriched Oracle Detection (ACM, Jun 2026):** New detection methods for price oracle manipulation across DeFi protocols. Relevant if TSAR integrates on-chain price feeds.

### 1.4 Container and Supply Chain

- **Docker Supply Chain Attacks (Docker Blog, Aug 2025):** MCP-based supply chain attacks targeting containerized AI systems. TSAR's Docker deployment is exposed if it ever mounts docker.sock or uses untrusted base images.

- **Container Runtime Vulnerabilities (2025-2026):** Multiple CVEs in container runtimes. TSAR's current Dockerfile uses `python:3.12-slim` which is good but needs regular rebuilding.

---

## 2. TSAR Vulnerability Assessment

### 2.1 Trading System Security — Score: 7/10

| Area | Status | Notes |
|------|--------|-------|
| API Key Storage | ✅ Good | Env vars, Fernet encryption in setup, no hardcoded keys |
| Sandbox Default | ✅ Excellent | `sandbox=True` default, paper mode default |
| Rate Limiting | ✅ Fixed | Local sliding window + ccxt built-in `enableRateLimit` |
| Retry Logic | ✅ Good | Freqtrade-style quadratic backoff, auth errors not retried |
| Order Validation | ✅ Good | Pydantic models, exchange limit checks before placement |
| IP Whitelisting | ❌ Missing | No guidance on exchange API key IP restrictions |
| Withdrawal Lock | ✅ Good | No `withdraw()` methods found in codebase |
| Front-Running Protection | ⚠️ Partial | No order flow obfuscation, no randomized timing |

**Remaining Issues:**
- **No IP whitelisting guidance:** Exchange API keys should be restricted to deployment IP. The setup wizard doesn't enforce or even mention this.
- **No order timing randomization:** Orders are placed at deterministic intervals, making them predictable to exchange-level front-running.
- **Single API key for read/write:** Best practice is separate keys for market data (read) and order placement (write) to limit blast radius.

### 2.2 AI Agent Security — Score: 5/10

| Area | Status | Notes |
|------|--------|-------|
| Prompt Injection Defense | ✅ Fixed | `sanitize_field()` with 13 patterns, output validation |
| Symbol Validation | ✅ Fixed | Regex `^[A-Z0-9/.-]{1,20}$` on signal symbols |
| Output Validation | ✅ Fixed | `validate_llm_output()` detects hijack patterns |
| Memory Poisoning | ❌ Missing | No validation on data written to SQLite/ChromaDB knowledge stores |
| LLM Output Trust Boundary | ⚠️ Partial | LLM outputs can influence trade decisions without human review |
| Model Supply Chain | ⚠️ Partial | Uses Ollama (local) by default, but cloud fallbacks (OpenAI, DeepSeek, NVIDIA) have no integrity verification |
| Adversarial Sentiment Attacks | ❌ Missing | SentimentAgent fetches from CryptoPanic and alternative.me with no data integrity checks |

**Critical Gap — Memory Poisoning:**
The `trade_memory`, `pattern_library`, `lesson_archive`, and `knowledge_graph` stores all accept data from LLM-processed trade reflections. An attacker who can influence trade outcomes (e.g., through a compromised data feed) can inject adversarial content into the knowledge base that persists across sessions and influences future trading decisions. This is the **memory poisoning** attack vector identified in the IBM report.

**Attack Chain:**
1. Attacker manipulates a market data feed to inject adversarial text in trade thesis
2. Trade executes, TradePhilosopher reflects on it with poisoned data
3. Reflection stored in `trade_records` with embedded adversarial instructions
4. Future `rag_blueprint_search` and `shadow_extractor` queries retrieve poisoned content
5. LLM agents make decisions influenced by poisoned knowledge base

**Mitigation Missing:** No data provenance tracking, no content integrity verification on knowledge store writes, no separation between trusted system data and untrusted external data.

### 2.3 Infrastructure Security — Score: 6/10

| Area | Status | Notes |
|------|--------|-------|
| Docker Non-Root | ✅ Excellent | `tsar` user (UID 1000), tini PID 1 |
| Config Read-Only | ✅ Good | `./config:/app/config:ro` |
| Health Checks | ✅ Good | API + Redis health checks |
| Resource Limits | ✅ Good | CPU/memory limits on all containers |
| Log Rotation | ✅ Good | json-file driver with size limits |
| TLS/HTTPS | ❌ Missing | No TLS termination, API runs plain HTTP |
| Redis Exposure | ❌ Risky | Port 6379 exposed to host, weak default password |
| Network Isolation | ⚠️ Partial | Bridge network, but no inter-container traffic encryption |
| Secret Rotation | ❌ Missing | Static secrets, no rotation mechanism |
| Dependency Scanning | ❌ Missing | No `cargo audit` or `pip-audit` in CI |
| Read-Only Root FS | ❌ Missing | Container filesystem is writable |
| Seccomp/AppArmor | ❌ Missing | No security profiles on containers |

**Critical Gap — No TLS:**
The API serves on plain HTTP. Even with Bearer token auth, credentials are transmitted in cleartext. For a trading system that controls real money, this is unacceptable for any non-localhost deployment.

**Critical Gap — Redis Exposure:**
Redis port 6379 is exposed to the host with a weak default password (`tsar_dev_password`). An attacker on the same network can read/write kill switch state, cached market data, and event streams.

### 2.4 Blockchain-Specific Security — Score: 5/10

| Area | Status | Notes |
|------|--------|-------|
| Smart Contract Interaction | ⚠️ N/A | TSAR uses CEX (Binance) via ccxt, not DEX |
| Wallet Security | ⚠️ N/A | No direct wallet management |
| Oracle Protection | ❌ Missing | No validation on external price feeds |
| Price Feed Integrity | ❌ Missing | Single-source price data from exchange API |
| Funding Rate Manipulation | ⚠️ Partial | SentimentAgent uses funding rates but no anomaly detection |

**Note:** TSAR is currently CEX-only. Blockchain-specific risks become critical if the system ever integrates DEX trading (Uniswap, Jupiter, etc.) or on-chain data feeds.

**Remaining Risk — Price Feed Manipulation:**
The SentimentAgent fetches Fear & Greed Index from `api.alternative.me` and news from `cryptopanic.com` without any integrity verification. A compromised or manipulated feed could inject adversarial sentiment data that influences trading decisions. The `sanitize_field()` function mitigates prompt injection through these feeds, but doesn't detect **semantic manipulation** (e.g., a flood of fake bearish news).

---

## 3. Hardening Recommendations

### Phase 1 — CRITICAL (Before Live Trading)

| # | Action | Impact | Effort |
|---|--------|--------|--------|
| 1 | **Add TLS termination** (nginx/caddy reverse proxy in docker-compose) | Prevents credential interception | 2h |
| 2 | **Remove Redis port exposure** — bind to 127.0.0.1 or remove host port mapping | Prevents external Redis access | 30m |
| 3 | **Add exchange API key IP whitelisting** documentation + setup enforcement | Limits key theft impact | 1h |
| 4 | **Add memory poisoning defense** — provenance tracking on knowledge store writes | Blocks persistent adversarial influence | 4h |
| 5 | **Add sentiment data anomaly detection** — detect sudden sentiment shifts that may indicate feed manipulation | Detects adversarial sentiment attacks | 2h |
| 6 | **Separate read/write exchange keys** — use read-only key for market data, write key only for order placement | Limits blast radius of key compromise | 1h |

### Phase 2 — HIGH (Before Production Scale)

| # | Action | Impact | Effort |
|---|--------|--------|--------|
| 7 | **Add `cargo audit` and `pip-audit` to CI** (`.github/workflows/ci.yml`) | Detects known vulnerabilities | 1h |
| 8 | **Add read-only root filesystem** to Docker (`read_only: true` + tmpfs for writable dirs) | Prevents filesystem-based attacks | 1h |
| 9 | **Add seccomp security profile** to Docker containers | Limits system call surface | 2h |
| 10 | **Add order timing randomization** — jitter on order placement to reduce predictability | Reduces front-running risk | 1h |
| 11 | **Add LLM output confidence scoring** — reject low-confidence LLM decisions that influence trades | Reduces adversarial LLM influence | 3h |
| 12 | **Add multi-source price validation** — cross-reference prices from 2+ sources before trading | Detects price feed manipulation | 3h |
| 13 | **Implement secret rotation** mechanism for API keys and Redis password | Reduces window of exposure from key compromise | 4h |
| 14 | **Add Grafana security defaults** — change admin password, disable sign-up (already partially done) | Prevents dashboard compromise | 30m |

### Phase 3 — MEDIUM (Ongoing Hardening)

| # | Action | Impact | Effort |
|---|--------|--------|--------|
| 15 | **Add structured security logging** with correlation IDs across agents | Enables incident forensics | 2h |
| 16 | **Implement circuit breaker on external data feeds** — auto-halt on anomalous data patterns | Detects coordinated attacks | 3h |
| 17 | **Add rate limiting on Telegram bot commands** (currently only API has rate limiting) | Prevents bot abuse | 1h |
| 18 | **Pin dependency versions** with lockfile (poetry.lock or pip-compile) | Prevents supply chain attacks | 1h |
| 19 | **Add SAST/DAST scanning** (Bandit for Python, cargo-audit for Rust) in CI | Automated vulnerability detection | 2h |
| 20 | **Implement data classification** — tag all data as trusted/untrusted, enforce boundaries | Systemic defense against injection | 8h |

---

## 4. Comparison with Prior Reviews

| Finding | CP1 (July 2026) | Security Officer (July 2026) | This Review (Aug 2026) |
|---------|-----------------|------------------------------|------------------------|
| API Authentication | 🔴 CRITICAL (none) | 🔴 CRITICAL | ✅ FIXED (Bearer token) |
| CORS Wildcard | 🔴 CRITICAL | 🔴 CRITICAL | ✅ FIXED (env-based) |
| Telegram Bot Auth | — | 🔴 CRITICAL | ✅ FIXED (chat ID whitelist) |
| Prompt Injection | — | 🟠 HIGH | ✅ FIXED (sanitization) |
| Weak Default Secrets | — | 🟠 HIGH | ✅ FIXED (startup validation) |
| Kill Switch Location | 🟠 HIGH (/tmp) | — | ✅ FIXED (./data/kill_switch) |
| Rate Limiting | 🟠 HIGH | 🟠 HIGH | ✅ FIXED (slowapi) |
| TLS/HTTPS | — | 🟠 HIGH | ❌ STILL MISSING |
| Redis Exposure | — | 🟡 MEDIUM | ❌ STILL MISSING |
| Memory Poisoning | — | — | 🆕 NEW FINDING |
| Sentiment Feed Integrity | — | — | 🆕 NEW FINDING |
| Order Timing Randomization | — | — | 🆕 NEW FINDING |
| Dependency Scanning in CI | — | 🟡 MEDIUM | ❌ STILL MISSING |

---

## 5. Positive Findings

TSAR has several **best-in-class** security features for a trading system:

| Feature | Assessment |
|---------|------------|
| **Kill Switch Architecture** | Exceptional — dual-write (file + Redis), fail-safe default, atomic writes, external kill capability, gated recovery protocol |
| **Mandate Authorization** | Excellent — default-deny, Pydantic validation, status lifecycle, order validation before execution |
| **Parameterized SQL** | Perfect — no SQL injection vectors found |
| **Fernet Secret Encryption** | Good — AES-128-CBC + HMAC-SHA256 for secret storage at rest |
| **Rust Safety** | Excellent — no `unsafe` blocks, no `unwrap()` in production paths (order-executor, ws-manager) |
| **Prompt Injection Defense** | Good — 13 injection patterns, output validation, field sanitization, truncation |
| **Sandbox-First Defaults** | Excellent — paper mode, sandbox exchange, fail-closed authentication |
| **Mobile App Security** | Good — HTTPS enforcement, SSL pinning framework, debug-mode bypass |

---

## 6. Verdict

### **CONDITIONAL PASS** ✅⚠️ — Score: 6.5/10

**Rationale:** TSAR has made significant security improvements since the CP1 review. All 5 critical/high findings have been fixed. The codebase demonstrates strong security awareness with defense-in-depth patterns (fail-safe kill switch, mandate authorization, prompt injection sanitization). However, the system still lacks TLS, has Redis exposure risks, has no memory poisoning defenses, and has no dependency scanning in CI.

**For paper trading with $10:** Safe. The API should not be exposed to any network, and the Telegram bot should be treated as semi-trusted.

**For live trading with real funds:** NOT SAFE until Phase 1 remediations are complete (TLS, Redis isolation, exchange key IP whitelisting, memory poisoning defense, sentiment feed validation, separate read/write keys).

**Estimated remediation effort:** 11h (Phase 1) + 19h (Phase 2) + 17h (Phase 3) = 47h total.

---

## 7. Research Sources

| Source | Date | Relevance |
|--------|------|-----------|
| TradeTrap: LLM Trading Agent Vulnerabilities (arXiv 2512.02261) | Dec 2025 | LLM prompt injection in trading |
| AI Agents in Cryptoland (arXiv 2503.16248) | Mar 2025 | Practical prompt injection on crypto agents |
| IBM Agentic AI Vulnerabilities Report | Aug 2025 | AI agent attack taxonomy |
| OWASP LLM Top 10 (2025) | 2025 | LLM security framework |
| MEV Formalization (ScienceDirect) | Mar 2026 | MEV attack strategies |
| OWASP Smart Contract Top 10 (2026) | 2026 | DeFi exploit taxonomy |
| Oracle Wars: Price Manipulation (CertiK) | May 2025 | DeFi oracle attack patterns |
| Event-Enriched Oracle Detection (ACM) | Jun 2026 | Oracle manipulation detection |
| Docker MCP Supply Chain Attack | Aug 2025 | Container security for AI |

---

*Report generated against OWASP Top 10 (2021), OWASP API Security Top 10 (2023), OWASP LLM Top 10 (2025), OWASP Smart Contract Top 10 (2026), and August 2026 threat intelligence.*
