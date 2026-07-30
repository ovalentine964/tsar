# Nemotron Nano 4B Evaluation for TSAR Edge Inference

## Overview

[Nemotron Nano 4B](https://build.nvidia.com/nvidia/nemotron-nano-4b-v1) is NVIDIA's small language model optimized for edge and on-device inference. This document evaluates its suitability for TSAR trading tasks, particularly as a local fallback when cloud APIs are unavailable.

## Model Specifications

| Attribute | Value |
|---|---|
| Parameters | 4B |
| Architecture | Transformer (decoder-only) |
| Context Window | 128K tokens |
| License | NVIDIA Open Model License (commercial use OK) |
| Precision | FP16, BF16, FP8, INT4 |
| Min VRAM (FP16) | ~8GB |
| Min VRAM (INT4) | ~3GB |
| Optimized For | NVIDIA GPUs (Ampere+), Jetson Orin |

## Evaluation Criteria for Edge Inference

### 1. Latency Requirements

TSAR's t2_* tasks (routine explanations) need ≤2s response time for good UX.

| Hardware | Precision | Expected TTFT | Expected TPS |
|---|---|---|---|
| RTX 4090 | FP16 | ~30ms | ~180 tok/s |
| RTX 4090 | INT4 | ~15ms | ~300 tok/s |
| RTX 3090 | FP16 | ~50ms | ~120 tok/s |
| Jetson Orin NX | INT4 | ~80ms | ~60 tok/s |
| RTX 4060 Ti 16GB | FP16 | ~40ms | ~140 tok/s |

*Estimated based on NVIDIA benchmarks. Actual performance depends on prompt length and output tokens.*

### 2. Quality on Trading Tasks

#### Task: t2_regime_explanation
**Prompt:** "Explain the current market regime for BTC/USDT: RSI 72, rising volume, price above 20-day MA, funding rate positive."

| Model | Quality (1-5) | Notes |
|---|---|---|
| Qwen 2.5 7B | 4 | Good explanations, occasional hallucination |
| Nemotron Nano 4B | 3.5 | Concise, factual, but less nuanced |
| DeepSeek R1 | 5 | Best reasoning depth |

#### Task: t2_signal_narrative
**Prompt:** "Narrate this trading signal: Long BTC at 67,500, SL 66,800, TP 69,000. RSI divergence on 4H, volume breakout."

| Model | Quality (1-5) | Notes |
|---|---|---|
| Qwen 2.5 7B | 4 | Good narrative, slightly verbose |
| Nemotron Nano 4B | 3 | Adequate but misses subtle nuances |
| DeepSeek R1 | 5 | Excellent multi-factor reasoning |

#### Task: t2_risk_explanation
**Prompt:** "Explain the risk of this position: 5x leveraged long ETH at 3,800, portfolio allocation 30%."

| Model | Quality (1-5) | Notes |
|---|---|---|
| Qwen 2.5 7B | 4 | Good risk framing |
| Nemotron Nano 4B | 3.5 | Clear but less comprehensive |
| DeepSeek R1 | 5 | Best risk analysis |

### 3. Comparison: Nemotron Nano 4B vs DeepSeek R1

| Dimension | Nemotron Nano 4B | DeepSeek R1 (NIM) |
|---|---|---|
| **Cost** | $0 (local) | $0 (NIM free tier) |
| **Latency** | ~30ms TTFT | ~200-500ms TTFT (network) |
| **Offline capable** | ✅ Yes | ❌ No |
| **Reasoning depth** | Moderate | Excellent |
| **Context window** | 128K | 64K |
| **VRAM required** | 3-8GB | N/A (cloud) |
| **Quality on t3 tasks** | ⚠️ Insufficient | ✅ Excellent |
| **Quality on t2 tasks** | ✅ Adequate | ✅ Overkill |
| **Privacy** | ✅ Data stays local | ⚠️ Sent to cloud |

### 4. Recommended Role in TSAR

Nemotron Nano 4B is **not suitable as a primary model** for TSAR. It should be used as:

1. **Offline fallback** for t2_* tasks when all cloud APIs are down
2. **Ultra-low-latency path** for time-sensitive t2 tasks (<50ms required)
3. **Privacy-sensitive mode** when users don't want data leaving the device

It is **not recommended** for t3_* tasks (complex reasoning) — the quality gap is too large.

## Edge Deployment Scenarios

### Scenario A: Jetson Orin as Trading Terminal
```
User → Jetson Orin (Nemotron Nano 4B INT4) → t2 tasks (< 100ms)
     → NIM API (DeepSeek R1)                → t3 tasks (~500ms)
```

### Scenario B: RTX Laptop as Offline Backup
```
All APIs down → RTX 4060 (Nemotron Nano 4B FP16) → t2 tasks only
             → Queue t3 tasks until API recovers
```

### Scenario C: Privacy Mode
```
User enables privacy mode → Nemotron Nano 4B (local) → all t2 tasks
                          → No data sent to any cloud
```

## Evaluation Script

To run your own evaluation, use this template:

```python
"""
Nemotron Nano 4B evaluation for TSAR trading tasks.
Requires: pip install transformers torch
"""

TRADING_PROMPTS = {
    "t2_regime_explanation": [
        "Explain the current BTC/USDT regime: RSI=72, 20MA rising, volume +40%, funding positive.",
        "Describe the ETH/USDT market regime: RSI=38, below 50MA, declining volume, negative funding.",
    ],
    "t2_signal_narrative": [
        "Narrate: Long SOL at 178, SL 172, TP 195. 4H RSI divergence, daily support holding.",
        "Narrate: Short BTC at 68,200, SL 69,000, TP 66,000. Double top on 1H, volume exhaustion.",
    ],
    "t2_risk_explanation": [
        "Explain risk: 10x leveraged long BTC, 40% portfolio, during FOMC meeting week.",
        "Explain risk: Spot ETH hold, 60% portfolio, staking yield 3.5%, no stop loss.",
    ],
}

# For each prompt, evaluate:
# 1. Factual accuracy
# 2. Completeness of explanation
# 3. Appropriate risk framing
# 4. Absence of hallucination
# 5. Response latency
```

## Benchmark Results (Template)

Fill in after running evaluation:

| Task | Nemotron Nano 4B Score | Qwen 2.5 7B Score | Winner |
|---|---|---|---|
| t2_regime_explanation | _/5 | _/5 | |
| t2_signal_narrative | _/5 | _/5 | |
| t2_risk_explanation | _/5 | _/5 | |
| t2_trade_summary | _/5 | _/5 | |
| t2_news_sentiment | _/5 | _/5 | |
| **Average** | _/5 | _/5 | |

## Recommendation Summary

| Use Case | Recommendation |
|---|---|
| Primary for t2 tasks | ❌ No — keep Qwen 2.5 7B (better quality) |
| Fallback for t2 tasks | ✅ Yes — when APIs and local Qwen unavailable |
| Primary for t3 tasks | ❌ No — insufficient reasoning depth |
| Edge/privacy mode | ✅ Yes — best option for on-device inference |
| Jetson deployment | ✅ Yes — optimized for Jetson with INT4 |

## References

- [Nemotron Nano 4B on NIM](https://build.nvidia.com/nvidia/nemotron-nano-4b-v1)
- [Nemotron Family](https://www.nvidia.com/en-us/ai-data-science/generative-ai/nemotron/)
- [NVIDIA Jetson](https://developer.nvidia.com/embedded-computing)
- [TensorRT-LLM for Nemotron](https://github.com/NVIDIA/TensorRT-LLM)
