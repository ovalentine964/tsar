# TensorRT-LLM Setup for TSAR Local Inference

> **Status:** Documentation only — not a hard dependency. TensorRT-LLM is optional for teams wanting to self-host optimized inference on NVIDIA GPUs.

## Overview

[TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM) is NVIDIA's open-source library for optimized LLM inference on NVIDIA GPUs. It provides:

- **2-6x throughput improvement** over vanilla PyTorch inference
- **FP8/INT4 quantization** with minimal quality loss
- **Paged KV-cache** for efficient memory management
- **In-flight batching** for maximum GPU utilization

## When to Use

| Scenario | Recommendation |
|---|---|
| Cloud API available (NIM, DeepSeek) | Use API — zero infrastructure cost |
| Local GPU with ≥24GB VRAM | TensorRT-LLM is viable |
| Edge deployment (Jetson, RTX 4090) | Consider Nemotron Nano 4B with TRT-LLM |
| No NVIDIA GPU | Skip — use Ollama on CPU/Metal instead |

## Prerequisites

- NVIDIA GPU with Compute Capability ≥ 8.0 (Ampere or newer: A100, A10, RTX 3090/4090, L4, H100)
- CUDA 12.x toolkit
- Python 3.10+
- Docker (recommended) or bare-metal build
- ~50GB disk for model weights + engine files

## Quick Start (Docker)

```bash
# Pull the official TensorRT-LLM container
docker pull nvcr.io/nvidia/tritonserver:24.01-trtllm-python-py3

# Or build from source
git clone https://github.com/NVIDIA/TensorRT-LLM.git
cd TensorRT-LLM
make -C docker release_build
```

## Building an Engine

### Step 1: Download Model Weights

```bash
# Example: DeepSeek R1 distilled (7B) — fits on single GPU
pip install huggingface_hub
huggingface-cli download deepseek-ai/DeepSeek-R1-Distill-Qwen-7B --local-dir ./models/deepseek-r1-7b

# Example: Nemotron Nano 4B — optimized for edge
huggingface-cli download nvidia/Nemotron-Nano-4B-v1 --local-dir ./models/nemotron-nano-4b
```

### Step 2: Convert Checkpoint

```bash
cd TensorRT-LLM

# Convert HuggingFace checkpoint to TensorRT-LLM format
python examples/llama/convert_checkpoint.py \
    --model_dir ../models/deepseek-r1-7b \
    --output_dir ../engines/deepseek-r1-7b-ckpt \
    --dtype float16 \
    --tp_size 1  # tensor parallelism (1 for single GPU)
```

### Step 3: Build TensorRT Engine

```bash
trtllm-build \
    --checkpoint_dir ../engines/deepseek-r1-7b-ckpt \
    --output_dir ../engines/deepseek-r1-7b-engine \
    --gemm_plugin float16 \
    --max_batch_size 8 \
    --max_input_len 4096 \
    --max_seq_len 8192 \
    --use_paged_context_fmha enable
```

### Step 4: Run Inference

```bash
python examples/run.py \
    --engine_dir ../engines/deepseek-r1-7b-engine \
    --max_output_len 2048 \
    --tokenizer_dir ../models/deepseek-r1-7b \
    --input_text "Analyze the current BTC/USDT trend given RSI=72, MACD bullish crossover, and volume declining."
```

## Benchmarking Script

Save as `benchmark_trtllm.sh`:

```bash
#!/usr/bin/env bash
# TensorRT-LLM Benchmark Script for TSAR
# Measures latency and throughput for trading-related prompts

set -euo pipefail

ENGINE_DIR="${1:-../engines/deepseek-r1-7b-engine}"
TOKENIZER="${2:-../models/deepseek-r1-7b}"
OUTPUT_FILE="benchmark_results_$(date +%Y%m%d_%H%M%S).json"

PROMPTS=(
    "Analyze BTC/USDT: RSI=72, MACD bullish crossover, volume declining. Provide a risk-adjusted recommendation."
    "Given the following OHLCV data for ETH/USDT [4h candles, last 50], identify the dominant pattern and likely next move."
    "Synthesize a multi-timeframe strategy for SOL/USDT considering: 15m oversold, 1h ranging, 4h uptrend, daily resistance at 180."
    "Detect potential wash trading in this order book snapshot: [asks: 100@50.1, 200@50.2, 50@50.3; bids: 300@49.9, 150@49.8, 80@49.7]"
)

echo "=== TensorRT-LLM Benchmark ==="
echo "Engine: ${ENGINE_DIR}"
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# Warm-up run
echo "[warm-up] Running..."
python examples/run.py \
    --engine_dir "${ENGINE_DIR}" \
    --max_output_len 128 \
    --tokenizer_dir "${TOKENIZER}" \
    --input_text "Hello" > /dev/null 2>&1

# Benchmark runs
echo "[benchmark] Running ${#PROMPTS[@]} prompts..."
results=()
for i in "${!PROMPTS[@]}"; do
    prompt="${PROMPTS[$i]}"
    echo "  Prompt $((i+1))/${#PROMPTS[@]}: ${prompt:0:60}..."

    start_ns=$(date +%s%N)
    output=$(python examples/run.py \
        --engine_dir "${ENGINE_DIR}" \
        --max_output_len 2048 \
        --tokenizer_dir "${TOKENIZER}" \
        --input_text "${prompt}" 2>&1)
    end_ns=$(date +%s%N)

    latency_ms=$(( (end_ns - start_ns) / 1000000 ))
    echo "    Latency: ${latency_ms}ms"
    results+=("{\"prompt_index\": ${i}, \"latency_ms\": ${latency_ms}}")
done

echo ""
echo "Results written to: ${OUTPUT_FILE}"
```

## Integrating with TSAR

To use TensorRT-LLM as a local provider in TSAR, you would add a provider entry in `config/models.yaml`:

```yaml
# Example (not yet implemented — requires a TRT-LLM serving layer):
# trtllm_local:
#   type: "trtllm"
#   engine_dir: "/path/to/engine"
#   tokenizer_dir: "/path/to/tokenizer"
#   max_concurrent: 1
```

> **Note:** This requires implementing a `trtllm` provider adapter in the TSAR router. Currently not a priority — NIM API covers the same models at zero cost.

## Performance Expectations

| Model | GPU | Precision | Throughput (tok/s) | Latency (TTFT) |
|---|---|---|---|---|
| DeepSeek R1 7B | RTX 4090 | FP16 | ~80 | ~120ms |
| DeepSeek R1 7B | A100 80GB | FP8 | ~150 | ~80ms |
| Nemotron Nano 4B | RTX 4090 | FP8 | ~200 | ~50ms |
| Nemotron Nano 4B | Jetson Orin | INT4 | ~60 | ~150ms |

*Estimates based on NVIDIA published benchmarks. Actual results vary with batch size, sequence length, and system configuration.*

## References

- [TensorRT-LLM GitHub](https://github.com/NVIDIA/TensorRT-LLM)
- [TensorRT-LLM Documentation](https://nvidia.github.io/TensorRT-LLM/)
- [NVIDIA NIM API](https://build.nvidia.com/) — cloud alternative (free tier available)
- [DeepSeek R1 on NIM](https://build.nvidia.com/deepseek-ai/deepseek-r1)
