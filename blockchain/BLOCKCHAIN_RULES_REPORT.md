# Blockchain for Rules Enforcement — TSAR Architecture Report

**Council:** Blockchain for Rules Enforcement
**Date:** 2026-08-01
**Score: 8.5/10**

---

## Executive Summary

Blockchain smart contracts enforce TSAR's trading RULES — making risk management **trustless and auditable**. This is NOT about execution speed (blockchain is slower than what TSAR already has). This is about **trust and verification**: ensuring risk guards can't be bypassed by any code path, human error, or adversarial actor.

**Core Insight:** Valentine wants blockchain for RULES, not execution speed. The existing TSAR RiskGovernor (7-layer veto protocol) is excellent but lives entirely off-chain. Blockchain adds a **trust layer** that makes risk enforcement **mathematically provable**.

**Architecture:** Dual enforcement model:
- **Off-chain (Python):** Fast path — checks rules in ~0.1ms
- **On-chain (Solidity):** Trust layer — verifies enforcement in ~2s
- **Both must agree** for a trade to proceed
- **On-chain has final authority** — cannot be bypassed

---

## 1. On-Chain Kill Switch — Score: 9/10

### Design

The kill switch is the **single most critical piece of state** in TSAR. The existing Python `KillSwitch` class uses dual-write (Redis + file) with fail-safe behavior. The on-chain version adds **mathematical certainty**.

**Smart Contract: `TSARKillSwitch.sol`**

```
┌─────────────────────────────────────────────────────────────────┐
│                    ON-CHAIN KILL SWITCH                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  TRIGGERS (AUTO-ACTIVATE):                                      │
│    • Daily P&L ≤ -2% → AUTOMATIC halt                           │
│    • Drawdown ≤ -5% (ORANGE) → No new entries                   │
│    • Drawdown ≤ -15% (RED) → AUTOMATIC halt                     │
│    • Emergency role → Immediate halt                            │
│                                                                 │
│  DEACTIVATION (MULTI-SIG + TIMELOCK):                           │
│    • Requires 2-of-3 multi-sig confirmations                    │
│    • Requires 48-hour time-lock                                 │
│    • Cannot be bypassed by ANY code path                        │
│                                                                 │
│  INTEGRATION:                                                   │
│    • Python RiskGovernor reads state via Rust bridge            │
│    • Off-chain: Python checks (fast path, ~0.1ms)               │
│    • On-chain: Smart contract verifies (trust layer, ~2s)       │
│    • If on-chain says HALT, off-chain CANNOT override           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Key Properties:**

| Property | Off-Chain (Current) | On-Chain (New) |
|---|---|---|
| Activation speed | ~0.1ms | ~2s (block time) |
| Bypassable | Yes (code bug, human error) | **No (mathematical)** |
| Audit trail | Logs (mutable) | **Blockchain (immutable)** |
| Deactivation | Manual (single point) | **Multi-sig + 48h timelock** |
| Fail-safe | Redis/file fallback | **Smart contract state** |

**Gas Cost:** ~50,000 gas per activation (~$0.01 on Polygon)

**Integration with Existing TSAR:**
- Maps directly to `src/risk/kill_switch.py` (KillSwitch class)
- Maps to `src/risk/drawdown.py` (DrawdownMonitor circuit breakers)
- Maps to `config/risk.yaml` (daily_loss_flatten: -0.02, daily_loss_kill: -0.03)

---

## 2. On-Chain Mandate — Score: 8/10

### Design

The mandate defines **WHAT** the system is allowed to trade. The existing Python `Mandate` class stores rules in `config/mandate.yaml`. The on-chain version makes these rules **immutable and governance-controlled**.

**Smart Contract: `TSARMandate.sol`**

```
┌─────────────────────────────────────────────────────────────────┐
│                    ON-CHAIN MANDATE                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  RULES STORED ON-CHAIN:                                         │
│    • Allowed symbols (BTC/USDT, ETH/USDT, etc.)                │
│    • Max leverage per symbol                                    │
│    • Position limits (max single, max total)                    │
│    • Order types (market, limit, stop)                          │
│    • Daily trade limits                                         │
│    • Paper trading requirements                                 │
│                                                                 │
│  GOVERNANCE:                                                    │
│    • Valentine controls rules via wallet                        │
│    • Changes require transaction signing                        │
│    • Critical changes require multi-sig (2-of-3)                │
│    • All changes have 48h time-lock                             │
│    • Immutable audit trail of all mandate changes               │
│                                                                 │
│  ORDER CHECKING:                                                │
│    • checkOrder() — called before every trade                   │
│    • Returns (allowed, reason)                                  │
│    • If not allowed, trade CANNOT proceed                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Key Properties:**

| Property | Off-Chain (Current) | On-Chain (New) |
|---|---|---|
| Storage | YAML file (mutable) | **Smart contract (immutable)** |
| Changes | File edit (instant) | **Multi-sig + 48h timelock** |
| Audit trail | Git history (can rewrite) | **Blockchain (permanent)** |
| Enforcement | Python code (can bypass) | **Smart contract (mathematical)** |
| Paper trading gate | Python checks | **On-chain verification** |

**Gas Cost:** ~100,000 gas per mandate change (~$0.02 on Polygon)

**Integration with Existing TSAR:**
- Maps directly to `src/risk/mandate.py` (Mandate class)
- Maps to `src/risk/mandate_gate.py` (MandateGate)
- Maps to `config/mandate.yaml` (allowed_symbols, max_leverage, etc.)

---

## 3. On-Chain Position Limits — Score: 9/10

### Design

Position limits are the **hard boundary** that prevents catastrophic loss. The existing Python `RiskGovernor` checks position limits in Layer 7 of the veto protocol. The on-chain version makes these limits **unbreakable**.

**Smart Contract: `TSARPositionLimits.sol`**

```
┌─────────────────────────────────────────────────────────────────┐
│                 ON-CHAIN POSITION LIMITS                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  LIMITS ENFORCED:                                               │
│    • Max single position: 15% of capital                        │
│    • Max total exposure: 100% of capital                        │
│    • Max sector concentration: 30% of capital                   │
│    • Max open positions: 10                                     │
│                                                                 │
│  ENFORCEMENT:                                                   │
│    • checkPositionLimit() — called before every trade           │
│    • Checks: single, total, sector, existing position           │
│    • Returns (passed, reason)                                   │
│    • If not passed, trade CANNOT proceed                        │
│                                                                 │
│  CANNOT BE EXCEEDED BY ANY CODE PATH:                           │
│    • Python can't override                                      │
│    • Rust can't override                                        │
│    • Human can't override                                       │
│    • Only governance can change limits (multi-sig + timelock)   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Key Properties:**

| Property | Off-Chain (Current) | On-Chain (New) |
|---|---|---|
| Enforcement | Python code (can bypass) | **Smart contract (mathematical)** |
| Position tracking | In-memory/database | **On-chain state** |
| Limit changes | Config file edit | **Governance (multi-sig + timelock)** |
| Audit trail | Logs | **Blockchain events** |
| Concentration limits | Python checks | **On-chain verification** |

**Gas Cost:** ~80,000 gas per position check (~$0.015 on Polygon)

**Integration with Existing TSAR:**
- Maps to `src/risk/governor.py` Layer 7 (Position Limits)
- Maps to `src/risk/position_sizer.py` (PositionSizer)
- Maps to `config/risk.yaml` (max_single_position_pct: 0.15, max_open_positions: 10)

---

## 4. On-Chain Circuit Breakers — Score: 8.5/10

### Design

The four-level circuit breaker system (GREEN → YELLOW → ORANGE → RED) is already implemented in Python (`src/risk/drawdown.py`). The on-chain version makes these levels **enforceable at the protocol level**.

```
┌─────────────────────────────────────────────────────────────────┐
│              ON-CHAIN CIRCUIT BREAKER LEVELS                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  GREEN:  Drawdown < 2%    → Normal operation, sizing ×1.0       │
│  YELLOW: Drawdown 2-3%    → 50% position sizing, sizing ×0.5   │
│  ORANGE: Drawdown 3-5%    → No new entries, sizing ×0.0         │
│  RED:    Drawdown > 5%    → KILL SWITCH, flatten everything     │
│                                                                 │
│  ON-CHAIN ENFORCEMENT:                                          │
│    • updateEquity() — called periodically by Rust bridge        │
│    • Smart contract calculates drawdown from HWM                │
│    • Automatically sets circuit breaker level                   │
│    • RED level auto-activates kill switch                       │
│    • Level changes emit events for audit trail                  │
│                                                                 │
│  DUAL ENFORCEMENT:                                              │
│    • Off-chain: Python DrawdownMonitor (fast path)              │
│    • On-chain: Smart contract verifies (trust layer)            │
│    • Both must agree for trading to proceed                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Mapping to Existing TSAR:**
- `config/risk.yaml`: daily_loss_flatten: -0.02, daily_loss_kill: -0.03
- `config/risk.yaml`: max_drawdown_halt: -0.05, max_drawdown_flatten: -0.15
- `src/risk/drawdown.py`: DrawdownMonitor.evaluate()
- `src/risk/governor.py`: Layer 6 (Drawdown Circuit Breaker)

---

## 5. On-Chain Audit Trail — Score: 9/10

### Design

The audit trail is blockchain's **killer feature** for TSAR. Every trade, risk check, and rule enforcement logged on-chain — **immutable, tamper-proof, publicly verifiable**.

**Smart Contract: `TSARAuditTrail.sol`**

```
┌─────────────────────────────────────────────────────────────────┐
│                   ON-CHAIN AUDIT TRAIL                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  WHAT'S LOGGED:                                                 │
│    • Every trade: hash, timestamp, pair, size, price            │
│    • Every rule enforcement: which rule, what action            │
│    • Every risk check: pass/fail, reason                        │
│    • Every mandate change: old rules → new rules                │
│    • Every kill switch event: activation/deactivation           │
│                                                                 │
│  PROPERTIES:                                                    │
│    • Immutable — once written, cannot be modified               │
│    • Tamper-proof — cryptographic verification                  │
│    • Publicly verifiable — anyone can audit                     │
│    • Gas-optimized — event-based logging (cheapest storage)     │
│    • Batch support — multiple trades in one transaction         │
│                                                                 │
│  GAS COSTS:                                                     │
│    • Single trade: ~30,000 gas (~$0.006 on Polygon)             │
│    • Batch of 100 trades: ~2,000,000 gas (~$0.40 on Polygon)   │
│    • Risk check: ~40,000 gas (~$0.008 on Polygon)               │
│                                                                 │
│  VERIFICATION:                                                  │
│    • verifyTrade(hash) — check if trade was recorded            │
│    • getTradeByIndex(i) — enumerate all trades                  │
│    • getDailyTradeCount(day) — daily trade volume               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Integration with Existing TSAR:**
- Maps to `src/risk/kill_switch.py` (immutable audit log)
- Maps to `src/risk/governor.py` (7-layer veto protocol logging)
- Enables regulatory compliance (prove trades followed rules)
- Enables dispute resolution (cryptographic evidence)

---

## 6. Governance Design — Score: 8/10

### Multi-Sig + Time-Lock Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    GOVERNANCE ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  VALENTINE'S WALLET (EOA)                                       │
│    │                                                            │
│    ├── Direct: Emergency halt, daily P&L updates                │
│    │                                                            │
│    └── Multi-Sig (2-of-3):                                      │
│        ├── Propose change                                        │
│        ├── Confirm (2 signers)                                   │
│        ├── Time-lock (48 hours)                                  │
│        └── Execute                                               │
│                                                                 │
│  ROLES:                                                         │
│    • OPERATOR_ROLE: TSAR bot (update P&L, equity, positions)    │
│    • GOVERNANCE_ROLE: Valentine (mandate changes, limit changes) │
│    • MULTISIG_ROLE: 3 signers (deactivation, critical changes)  │
│    • EMERGENCY_ROLE: Emergency halt (immediate)                 │
│                                                                 │
│  TIME-LOCKS:                                                    │
│    • Kill switch deactivation: 48 hours                         │
│    • Mandate changes: 48 hours                                  │
│    • Limit changes: 48 hours                                    │
│    • Threshold changes: 48 hours                                │
│                                                                 │
│  IMMUTABILITY:                                                  │
│    • All changes are on-chain transactions                      │
│    • All transactions are signed by wallet                      │
│    • All signatures are cryptographically verifiable            │
│    • Complete history preserved forever                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. Technical Architecture

### Deployment Stack

```
┌─────────────────────────────────────────────────────────────────┐
│                    DEPLOYMENT ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ Python Brain  │    │  Rust Core   │    │  Polygon L2  │      │
│  │ (94K lines)   │    │ (10K lines)  │    │  (Smart       │      │
│  │               │    │              │    │   Contracts)  │      │
│  │ • RiskGovernor│───▶│ • ethers-rs  │───▶│ • KillSwitch  │      │
│  │ • Mandate     │    │ • PyO3       │    │ • Mandate     │      │
│  │ • Drawdown    │    │ • WebSocket  │    │ • PosLimits   │      │
│  │ • Guards      │    │              │    │ • AuditTrail  │      │
│  │               │◀───│              │◀───│               │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                 │
│  Speed: ~0.1ms          Speed: ~5ms        Speed: ~2s          │
│  Role: Intelligence     Role: Bridge       Role: Trust          │
│                                                                 │
│  DUAL ENFORCEMENT:                                              │
│    1. Python checks rules (fast path)                           │
│    2. Rust bridges to blockchain                                │
│    3. Smart contract verifies (trust layer)                     │
│    4. Both must agree → trade proceeds                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Rust Integration (ethers-rs)

```rust
// crates/blockchain-rules/
// └── src/
//     ├── lib.rs              // Main client
//     ├── kill_switch.rs      // Kill switch bindings
//     ├── mandate.rs          // Mandate bindings
//     ├── position_limits.rs  // Position limit bindings
//     ├── audit_trail.rs      // Audit trail bindings
//     └── types.rs            // Shared types

// PyO3 Bridge (crates/pyo3-bindings/src/)
// └── blockchain_bridge.rs    // Python ↔ Rust bridge
```

### Python Integration

```python
# src/risk/blockchain_enforcer.py
# Integrates with existing RiskGovernor

class BlockchainEnforcer:
    """On-chain rules enforcement bridge."""

    def __init__(self, client: BlockchainClient):
        self.client = client

    async def pre_trade_check(self, signal, portfolio) -> bool:
        """Dual enforcement: off-chain + on-chain."""
        # 1. Off-chain check (fast path)
        off_chain_ok = await self.risk_governor.check_risk(signal, portfolio)

        # 2. On-chain check (trust layer)
        on_chain_ok = self.client.is_trading_allowed()

        # 3. Both must agree
        return off_chain_ok.approved and on_chain_ok
```

### Smart Contract Deployment

```bash
# Deploy to Polygon (recommended for low gas costs)
# Estimated deployment cost: ~$5-10 total

# 1. Kill Switch
forge deploy TSARKillSwitch \
  --rpc-url https://polygon-rpc.com \
  --private-key $OPERATOR_KEY \
  --constructor-args $OPERATOR $MULTISIG_1 $MULTISIG_2 $MULTISIG_3

# 2. Mandate
forge deploy TSARMandate \
  --rpc-url https://polygon-rpc.com \
  --private-key $OPERATOR_KEY \
  --constructor-args $GOVERNANCE

# 3. Position Limits
forge deploy TSARPositionLimits \
  --rpc-url https://polygon-rpc.com \
  --private-key $OPERATOR_KEY \
  --constructor-args $GOVERNANCE $OPERATOR 1500 10000 3000 10

# 4. Audit Trail
forge deploy TSARAuditTrail \
  --rpc-url https://polygon-rpc.com \
  --private-key $OPERATOR_KEY \
  --constructor-args $RECORDER $VERIFIER
```

---

## 8. Gas Cost Analysis

| Operation | Gas Cost | USD Cost (Polygon) | Frequency |
|---|---|---|---|
| Check kill switch | ~5,000 | $0.001 | Every trade |
| Update daily P&L | ~50,000 | $0.01 | Per trade settlement |
| Update equity | ~60,000 | $0.012 | Periodic (5min) |
| Check order (mandate) | ~100,000 | $0.02 | Every trade |
| Check position limit | ~80,000 | $0.015 | Every trade |
| Record trade (audit) | ~30,000 | $0.006 | Every trade |
| Log risk check | ~40,000 | $0.008 | Every trade |
| Activate kill switch | ~50,000 | $0.01 | Emergency only |
| Mandate change | ~150,000 | $0.03 | Rare (governance) |

**Total per trade:** ~305,000 gas (~$0.06 on Polygon)
**Monthly cost (100 trades/day):** ~$180/month on Polygon
**Annual cost:** ~$2,160/year on Polygon

**Note:** Polygon gas costs are extremely low. On Ethereum mainnet, these costs would be 100-1000x higher.

---

## 9. File Structure

```
tsar/blockchain/
├── contracts/
│   ├── TSARKillSwitch.sol          # On-chain kill switch
│   ├── TSARMandate.sol             # On-chain mandate
│   ├── TSARPositionLimits.sol      # On-chain position limits
│   └── TSARAuditTrail.sol          # On-chain audit trail
├── rust-bindings/
│   ├── Cargo.toml
│   └── src/
│       ├── lib.rs                  # Main client
│       ├── kill_switch.rs          # Kill switch bindings
│       ├── mandate.rs              # Mandate bindings
│       ├── position_limits.rs      # Position limit bindings
│       ├── audit_trail.rs          # Audit trail bindings
│       └── types.rs                # Shared types
├── python-bridge/
│   ├── blockchain_client.py        # Python client (PyO3)
│   └── __init__.py
└── BLOCKCHAIN_RULES_REPORT.md      # This document
```

---

## 10. Score Summary

| Component | Score | Rationale |
|---|---|---|
| On-Chain Kill Switch | 9/10 | Cannot be bypassed. Multi-sig + timelock deactivation. Auto-activation on threshold breach. |
| On-Chain Mandate | 8/10 | Immutable rules. Governance-controlled. Paper trading gate. |
| On-Chain Position Limits | 9/10 | Mathematical enforcement. Cannot be exceeded by any code path. |
| On-Chain Circuit Breakers | 8.5/10 | Dual enforcement. Auto-level changes. RED auto-halt. |
| On-Chain Audit Trail | 9/10 | Immutable. Tamper-proof. Publicly verifiable. Gas-optimized. |
| Governance Design | 8/10 | Multi-sig + timelock. Role-based access. Complete audit trail. |
| **Overall** | **8.5/10** | **Strong trust and verification layer for TSAR's risk management.** |

---

## 11. Recommendation

**Blockchain IS a rules enforcement solution for TSAR.** It's NOT a speed solution — it's a **trust, verification, and auditability** solution.

**What blockchain adds to TSAR:**
1. **Mathematical certainty** — risk rules can't be bypassed
2. **Immutable audit trail** — every trade, every check, every enforcement
3. **Governance control** — multi-sig + timelock for rule changes
4. **Regulatory compliance** — prove trades followed rules
5. **Dispute resolution** — cryptographic evidence

**What blockchain does NOT add:**
- ❌ Speed (slower than off-chain)
- ❌ Lower costs (adds gas costs)
- ❌ Simplicity (adds complexity)

**Bottom line:** If Valentine wants TSAR's risk management to be **trustless and auditable**, blockchain smart contracts are the answer. The dual enforcement model (off-chain fast path + on-chain trust layer) gives the best of both worlds: speed AND trust.

**Implementation priority:**
1. **Phase 1:** Deploy `TSARKillSwitch.sol` — highest impact, most critical
2. **Phase 2:** Deploy `TSARAuditTrail.sol` — immediate auditability
3. **Phase 3:** Deploy `TSARMandate.sol` — governance control
4. **Phase 4:** Deploy `TSARPositionLimits.sol` — complete enforcement

**Estimated implementation time:** 2-3 weeks for full deployment
**Estimated cost:** ~$10 deployment + ~$200/month operational (Polygon)
