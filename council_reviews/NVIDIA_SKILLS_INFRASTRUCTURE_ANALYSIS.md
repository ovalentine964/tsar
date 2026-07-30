# NVIDIA Skills: Infrastructure & Performance Analysis for TSAR

**Analyst:** NVIDIA Skills Infrastructure & Performance Analyst  
**Date:** 2026-07-30  
**Scope:** 18 NVIDIA Agent Skills across GPU Development, Infrastructure, and Inference AI  
**Context:** TSAR Python + Rust + C++ stack with CUDA kernel stubs, Docker deployment

---

## Executive Summary

NVIDIA's official `npx skills add nvidia/skills` catalog provides **18 directly relevant skills** for TSAR's GPU journey. These skills are instruction sets that teach AI coding agents how to use NVIDIA software optimally — they're not libraries, but **expert workflows** baked into your development environment.

The skills divide into three tiers of TSAR relevance:

| Priority | Category | Skills Count | TSAR Impact |
|----------|----------|:---:|-------------|
| 🔴 Critical | GPU Development (TileGym/cuTile) | 7 | Core kernel performance |
| 🟡 Important | Infrastructure (TAO/Holoscan) | 7 | Deployment & scaling |
| 🟢 Useful | Inference AI (Jetson) | 4 | Edge inference optimization |

---

## Category 1: GPU Development — TileGym / cuTile Skills

### Understanding TileGym & cuTile

**TileGym** is NVIDIA's project for providing performant GPU kernels for LLM training and inference. **cuTile** (formerly "cuda.tile") is a Python-based DSL for writing tile-based GPU kernels that automatically leverage tensor cores — without writing raw CUDA C.

This is **the single most impactful skill category for TSAR** because it directly addresses kernel performance.

---

### 1. tilegym-cutile-python — cuTile Programming Fundamentals

**What it does:**  
A comprehensive cuTile programming assistant. Teaches the agent how to write high-performance GPU kernels using cuTile's tile-based programming model, including the execution model, data/memory models, debugging, compilation, and every public API operation (load/store, reductions, scans, matmul, atomics, autotuning).

**Why it matters for TSAR:**  
This is the **foundational skill** for all GPU work. TSAR currently has CUDA kernel stubs — this skill enables writing production kernels in Python (not CUDA C) that automatically target tensor cores. The cuTile DSL abstracts away thread/block management while still generating high-performance code.

**TSAR integration point:**  
- `src/tsar/kernels/` — write cuTile implementations of existing stub kernels
- Replace PyTorch reference implementations with cuTile-optimized versions
- Any compute-heavy Python module can get a cuTile backend

**When to adopt:** 🟢 **Immediately (even before GPU hardware)**  
- Can prototype and validate on any NVIDIA GPU
- The skill includes examples and patterns that work on consumer GPUs

**Hardware requirements:**  
- Any NVIDIA GPU with CUDA support (RTX 4060 minimum, works on any Ampere+)
- cuTile Python SDK (part of CUDA Toolkit 13.0+)

---

### 2. tilegym-adding-cutile-kernel — Adding New CUDA Kernels

**What it does:**  
End-to-end workflow for adding a new operator to TileGym with a cuTile backend. Covers: dispatch registration in `ops.py`, cuTile backend implementation, `__init__.py` export, test creation, benchmark creation, and verification (pytest + lint).

**Why it matters for TSAR:**  
When TSAR needs a custom kernel (e.g., a specialized attention variant, a custom activation, or a domain-specific reduction), this skill provides the **structured workflow** to add it correctly. The 6-step checklist ensures nothing is missed — dispatch registration, implementation, export, testing, benchmarking, and verification.

**TSAR integration point:**  
- Each new TSAR kernel op gets added following this exact pattern
- The `@dispatch` decorator pattern maps cleanly to TSAR's existing kernel stub structure
- Tests and benchmarks come for free with the workflow

**When to adopt:** 🟢 **Immediately** — adopt the pattern for all kernel development from day one

**Hardware requirements:**  
- Same as cuTile-python: any NVIDIA GPU with CUDA 13.0+

---

### 3. tilegym-cutile-autotuning — Kernel Autotuning

**What it does:**  
Adds autotuning to cuTile kernels using the `exhaustive_search` API with a tune-once/cache/direct-launch pattern. Handles occupancy-only tuning for elementwise/reduction kernels, and full tile-size search for matmul/FMHA/FP8 kernels. Includes 9 kernel-type templates (T1-T9) and a decision tree for classification.

**Why it matters for TSAR:**  
Autotuning is the difference between a "working" kernel and an **optimal** kernel. The tune-once/cache pattern means the first invocation searches for the best config, then all subsequent calls use the cached winner with zero overhead. This skill handles the notoriously tricky pitfalls: in-place kernel data corruption, compilation timeouts, empty search spaces, and the `replace_hints` hot-path trap.

**TSAR integration point:**  
- Every cuTile kernel in TSAR should use this autotuning pattern
- The cache key pattern `(shape, dtype, device)` ensures different tensor configurations each get their optimal config
- Critical for production: `exhaustive_search` runs once, then `ct.launch` with cached config

**When to adopt:** 🟢 **Immediately** — build into every kernel from the start

**Hardware requirements:**  
- Any NVIDIA GPU (search space scales with architecture; sm100+ has expanded coverage)

---

### 4. tilegym-improve-cutile-kernel-perf — Iterative Performance Optimization

**What it does:**  
Systematic profiling, bottleneck diagnosis, and iterative tuning workflow. Three phases: Setup (baseline measurement), Experimentation loop (one optimization per iteration, 10-minute limit each), and convergence. Classifies kernels as memory-bound (AI<10), balanced (AI 10-50), or compute-bound (AI>50). Includes optimization playbooks (A through J), performance knobs catalog, IR dump analysis, and a perf-results tracking table.

**Why it matters for TSAR:**  
This is the **performance engineering skill**. When a kernel works but isn't fast enough, this skill provides the systematic approach: profile → diagnose → apply one optimization → verify correctness → benchmark → repeat. The optimization playbook covers tile sizes, TMA usage, persistent scheduling, occupancy, latency hints, and more.

**TSAR integration point:**  
- Run this on every critical-path kernel before declaring it "done"
- The `@sandbox/perf_results.md` tracking table gives visibility into optimization progress
- The 10-minute-per-iteration constraint prevents rabbit holes

**When to adopt:** 🟡 **At $1K milestone (RTX 4060)** — when kernel performance becomes measurable

**Hardware requirements:**  
- NVIDIA GPU (Blackwell or Ampere recommended for full playbook)
- Nsight Compute for IR dump analysis (optional but recommended)

---

### 5. tilegym-converting-cutile-to-triton — cuTile → Triton Conversion

**What it does:**  
Converts `@ct.kernel` cuTile kernels to `@triton.jit` Triton kernels. Handles the full API mapping, TMA descriptor creation, advanced patterns (transpose, dual layouts, MLA-style paths), and performance debugging for 10-50× slowdowns. Includes special handling for attention/FMHA/GQA kernels.

**Why it matters for TSAR:**  
Triton is the dominant kernel authoring framework (used by PyTorch, vLLM, etc.). Having cuTile kernels is great for NVIDIA hardware, but **Triton kernels are more portable** and have a larger ecosystem. This skill lets TSAR prototype in cuTile (easier Python DSL) and then convert to Triton for broader deployment.

**TSAR integration point:**  
- Prototype kernels in cuTile → convert to Triton for production
- The two-kernel + META grid pattern handles complex transpose cases
- Critical: `tl.make_tensor_descriptor` (TMA) for 2D+ block loads, not raw `tl.load`

**When to adopt:** 🟡 **At $1K milestone** — when you need to optimize for specific hardware or want broader compatibility

**Hardware requirements:**  
- NVIDIA GPU with Triton support (Ampere+)
- Triton installed (`pip install triton`)

---

### 6. tilegym-converting-cutile-to-julia — cuTile → Julia Conversion

**What it does:**  
Converts cuTile GPU kernels to Julia (likely via CUDA.jl or KernelAbstractions.jl). Handles the language translation patterns and Julia-specific GPU programming idioms.

**Why it matters for TSAR:**  
**Low priority for TSAR.** Unless TSAR adopts Julia for numerical computing, this skill has limited applicability. However, if TSAR ever needs to integrate with Julia-based scientific computing ecosystems, this would be the bridge.

**TSAR integration point:**  
- Not directly applicable unless TSAR adds a Julia component
- Could be useful for benchmarking against Julia GPU implementations

**When to adopt:** ⚪ **Defer** — only if Julia adoption becomes a requirement

**Hardware requirements:**  
- Same as cuTile skills + Julia installation

---

### 7. tilegym-monkey-patch-kernels-to-transformers — Kernel → Transformers Integration

**What it does:**  
Integrates TileGym kernels into Hugging Face `transformers` models via monkey-patching — replacing the library's submodule implementations without modifying transformers source code. Includes an auto-research-style agent harness loop to create and integrate new cuTile kernels for uncovered PyTorch code paths, targeting end-to-end throughput improvement.

**Why it matters for TSAR:**  
If TSAR uses any Hugging Face models (likely, given the LLM inference path), this skill **directly accelerates inference** by replacing slow PyTorch implementations with optimized cuTile kernels. The monkey-patch approach means no fork of transformers — just runtime replacement.

**TSAR integration point:**  
- Any `transformers` model loading in TSAR can be accelerated
- The auto-kernelize loop finds and replaces bottleneck operations automatically
- Non-intrusive: works alongside stock transformers

**When to adopt:** 🟡 **At $1K milestone** — when TSAR starts running transformer models for inference

**Hardware requirements:**  
- NVIDIA GPU with cuTile support
- Hugging Face transformers installed

---

## Category 2: Infrastructure — Deployment & Scaling

### Understanding the TAO/Holoscan Ecosystem

**TAO (Train, Adapt, Optimize)** is NVIDIA's transfer learning toolkit for fine-tuning and deploying AI models. **Holoscan** is NVIDIA's real-time AI processing platform for sensor data. These skills handle the "last mile" of getting GPU workloads running in production.

---

### 8. tao-setup-nvidia-gpu-host — GPU Host Setup

**What it does:**  
Standardizes a Linux host's GPU runtime: installs NVIDIA driver branch 580, CUDA Toolkit 13.0, and NVIDIA Container Toolkit 1.19.0. Supports Debian/Ubuntu, RHEL/Fedora, and SUSE families. Safe check-only mode (read-only) and explicit install mode with user approval.

**Why it matters for TSAR:**  
This is the **prerequisite for everything else**. Before any GPU container can run, the host needs the correct driver, CUDA toolkit, and container toolkit versions. This skill automates what is normally a painful manual process.

**TSAR integration point:**  
- Run on every new GPU machine (cloud VM, bare metal, DGX Spark)
- The `--check-only` mode is safe for CI/CD validation
- Ensures Docker can access GPUs via `--gpus all`

**When to adopt:** 🟢 **Immediately** — first thing to run on any new GPU machine

**Hardware requirements:**  
- Any NVIDIA GPU
- Linux host (Ubuntu 22.04/24.04, RHEL 9/10, openSUSE)

---

### 9. tao-run-on-brev — Run on NVIDIA Brev

**What it does:**  
Executes TAO workloads on NVIDIA Brev (cloud GPU platform). Handles Brev instance provisioning, environment setup, and job submission for training/inference workloads.

**Why it matters for TSAR:**  
Brev provides **on-demand GPU access** without managing infrastructure. Useful for TSAR when you need to test on hardware you don't own yet (e.g., validating on A100/H100 before purchasing).

**TSAR integration point:**  
- Use for burst capacity testing before hardware purchases
- Validate TSAR performance on different GPU tiers
- Cost-effective way to benchmark on high-end GPUs

**When to adopt:** 🟢 **Immediately** — useful for pre-purchase GPU validation

**Hardware requirements:**  
- Brev account (cloud-based, no local GPU needed)

---

### 10. tao-run-on-kubernetes — K8s Deployment

**What it does:**  
Submits TAO container jobs as Kubernetes Jobs. Works on any cluster (EKS/GKE/AKS/on-prem). Supports single-pod and multi-node distributed training via Indexed Job + headless Service. Handles GPU Operator/device plugin verification, NGC image pulls, and S3 dataset I/O.

**Why it matters for TSAR:**  
Kubernetes is the standard for **scaling GPU workloads**. When TSAR moves beyond single-machine development, this skill handles the complexity of GPU scheduling, multi-node training, and container orchestration.

**TSAR integration point:**  
- TSAR Docker containers → K8s Jobs with GPU resource requests
- Multi-node training for large models
- S3 integration for dataset management
- Works with TSAR's existing Docker deployment

**When to adopt:** 🟡 **At $10K milestone (RTX 4090 / multi-GPU)** — when scaling beyond single machine

**Hardware requirements:**  
- Kubernetes cluster with NVIDIA GPU Operator
- At least one GPU node
- kubeconfig access

---

### 11. tao-run-on-slurm — Slurm Deployment

**What it does:**  
Runs TAO workloads on Slurm-managed HPC clusters. Handles job submission, GPU allocation, and resource scheduling in traditional HPC environments.

**Why it matters for TSAR:**  
Slurm is common in **academic and research HPC environments**. If TSAR runs on university or lab clusters, this skill handles the Slurm integration. Less relevant for cloud-native deployments.

**TSAR integration point:**  
- Submit TSAR training jobs to Slurm-managed GPU clusters
- Useful for accessing shared institutional GPU resources

**When to adopt:** ⚪ **Defer** — only if TSAR needs HPC cluster access

**Hardware requirements:**  
- Slurm-managed cluster with GPU nodes

---

### 12. holoscan-setup — Holoscan SDK Setup

**What it does:**  
Installs and sets up the Holoscan SDK on any platform (container, Debian, Python, Conda, or source). Acts as the meta-skill that dispatches to the correct installation method.

**Why it matters for TSAR:**  
Holoscan is for **real-time sensor processing** — relevant if TSAR has any pipeline that processes streaming data (video, sensor feeds). The setup skill ensures the SDK is correctly installed before any Holoscan application development.

**TSAR integration point:**  
- Only relevant if TSAR has real-time data processing requirements
- Could accelerate any streaming inference pipeline

**When to adopt:** ⚪ **Defer** — only if TSAR needs real-time sensor processing

**Hardware requirements:**  
- NVIDIA GPU (Ampere+ recommended for Holoscan)

---

### 13. holoscan-install-conda — Holoscan Conda Install

**What it does:**  
Installs Holoscan SDK via Conda package manager. Handles environment creation, dependency resolution, and GPU passthrough validation within Conda environments.

**Why it matters for TSAR:**  
If TSAR uses Conda for environment management (common in Python ML stacks), this provides a clean Holoscan installation path without Docker overhead.

**TSAR integration point:**  
- Alternative to Docker-based Holoscan installation
- Better for development iteration (no container rebuild)

**When to adopt:** ⚪ **Defer** — only alongside holoscan-setup

**Hardware requirements:**  
- NVIDIA GPU + Conda

---

### 14. holoscan-install-container — Holoscan Container Install

**What it does:**  
Pulls and verifies the official Holoscan SDK container from NGC (`nvcr.io/nvidia/clara-holoscan/holoscan`). Handles tag selection based on CUDA version (cuda13/cuda12-dgpu/cuda12-igpu), GPU passthrough verification, and validation with six example applications.

**Why it matters for TSAR:**  
The container approach is **cleanest for production** — reproducible, isolated, and includes all dependencies. The tag selection logic (matching container CUDA version to host driver) prevents the common "CUDA init failure" error.

**TSAR integration point:**  
- Base image for TSAR's Holoscan-based workloads
- The validation examples confirm GPU passthrough works
- Docker flags for production: `--runtime=nvidia --gpus all --ipc=host`

**When to adopt:** ⚪ **Defer** — only alongside Holoscan adoption

**Hardware requirements:**  
- NVIDIA GPU with working driver
- Docker + NVIDIA Container Toolkit
- 10-20 GB disk for image

---

## Category 3: Inference AI — Jetson Skills

### Understanding Jetson Relevance

Jetson is NVIDIA's edge AI platform. While TSAR likely targets discrete GPUs primarily, these skills are relevant for **edge deployment scenarios** and **inference optimization patterns** that apply broadly.

---

### 15. jetson-inference-mem-tune — Inference Memory Tuning

**What it does:**  
Tunes memory allocation and management for LLM inference on Jetson devices. Handles GPU memory limits, KV cache sizing, and memory-efficient inference configurations.

**Why it matters for TSAR:**  
Memory tuning principles apply beyond Jetson. When TSAR runs on memory-constrained GPUs (RTX 4060 with 8GB), the same techniques for KV cache management and memory-efficient inference are directly applicable.

**TSAR integration point:**  
- Apply memory tuning patterns to TSAR's inference pipeline
- Critical for fitting models into 8GB (RTX 4060) or 24GB (RTX 4090)
- KV cache optimization for long-context inference

**When to adopt:** 🟡 **At $1K milestone (RTX 4060)** — memory is tight on 8GB

**Hardware requirements:**  
- Any NVIDIA GPU (patterns apply broadly)

---

### 16. jetson-llm-benchmark — LLM Benchmarking

**What it does:**  
Reproducible LLM benchmarks with structured JSON output. Supports vLLM, llama.cpp, and Ollama runtimes. Measures latency (TTFT, ITL/TPOT) and throughput across different configurations.

**Why it matters for TSAR:**  
**You can't optimize what you can't measure.** This skill provides standardized benchmarking that produces machine-readable JSON results. Essential for comparing TSAR's performance before/after optimizations, across GPU tiers, and against baselines.

**TSAR integration point:**  
- Benchmark TSAR's inference performance at each hardware milestone
- Compare vLLM vs llama.cpp vs custom runtime
- JSON output enables automated regression testing
- Before/after kernel optimization validation

**When to adopt:** 🟢 **Immediately** — benchmark from day one, even on CPU

**Hardware requirements:**  
- Any NVIDIA GPU for meaningful benchmarks
- vLLM/llama.cpp/Ollama installed

---

### 17. jetson-llm-serve — LLM Serving

**What it does:**  
Configures and deploys LLM serving on Jetson devices using vLLM, llama.cpp, or Ollama. Handles model loading, serving configuration, and API endpoint setup.

**Why it matters for TSAR:**  
If TSAR needs to serve models (likely), this skill provides the deployment patterns. While Jetson-specific, the serving configurations (batching, concurrency, model loading) apply to any NVIDIA GPU deployment.

**TSAR integration point:**  
- Deploy TSAR's inference API using vLLM or llama.cpp
- Optimize serving configuration for target GPU
- OpenAI-compatible API endpoint for easy integration

**When to adopt:** 🟡 **At $1K milestone** — when TSAR needs to serve models

**Hardware requirements:**  
- NVIDIA GPU with sufficient VRAM for target model

---

### 18. jetson-speculative-decoding — Speculative Decoding

**What it does:**  
Implements speculative decoding for LLM inference — using a small "draft" model to generate candidate tokens that are then verified by the larger "target" model in parallel. Can achieve 2-3× speedup on latency-sensitive inference.

**Why it matters for TSAR:**  
Speculative decoding is one of the **highest-impact inference optimizations** available. It reduces latency without changing model quality. The skill handles the draft model selection, verification logic, and acceptance criteria.

**TSAR integration point:**  
- Apply to TSAR's LLM inference pipeline for 2-3× latency improvement
- Works with any autoregressive model
- Especially valuable on RTX 4090 (24GB) where both draft and target models fit

**When to adopt:** 🟡 **At $10K milestone (RTX 4090)** — need enough VRAM for two models

**Hardware requirements:**  
- Sufficient VRAM for draft + target model
- Best on RTX 4090 (24GB) or DGX Spark (larger memory)

---

## Integration Roadmap by Capital Milestone

### 🟢 Phase 1: Pre-GPU / $0 (Now)

**Adopt immediately — no hardware required:**

| Skill | Action | Value |
|-------|--------|-------|
| `tilegym-cutile-python` | Learn cuTile patterns, write prototype kernels | Foundation for all GPU work |
| `tilegym-adding-cutile-kernel` | Adopt the 6-step workflow for kernel development | Structured kernel development |
| `tilegym-cutile-autotuning` | Build autotuning into every kernel from start | Never ship untuned kernels |
| `tao-setup-nvidia-gpu-host` | Document the setup procedure for future machines | Ready for GPU day one |
| `tao-run-on-brev` | Validate TSAR on cloud GPUs before purchasing | Risk reduction |
| `jetson-llm-benchmark` | Set up benchmarking framework | Measure everything from day one |

**Install command:**
```bash
npx skills add nvidia/skills \
  --skill tilegym-cutile-python \
  --skill tilegym-adding-cutile-kernel \
  --skill tilegym-cutile-autotuning \
  --skill tao-setup-nvidia-gpu-host \
  --skill tao-run-on-brev \
  --skill jetson-llm-benchmark \
  --yes
```

---

### 🟡 Phase 2: RTX 4060 at $1K

**8GB VRAM — memory-constrained, focus on efficiency:**

| Skill | Action | Value |
|-------|--------|-------|
| `tilegym-improve-cutile-kernel-perf` | Optimize kernels for 4060's constraints | Max perf per watt/GB |
| `tilegym-converting-cutile-to-triton` | Convert critical kernels to Triton | Portability + ecosystem |
| `tilegym-monkey-patch-kernels-to-transformers` | Accelerate HF model inference | Direct inference speedup |
| `jetson-inference-mem-tune` | Apply memory tuning for 8GB | Fit models in limited VRAM |
| `jetson-llm-serve` | Set up model serving | Inference API |

**Additional install:**
```bash
npx skills add nvidia/skills \
  --skill tilegym-improve-cutile-kernel-perf \
  --skill tilegym-converting-cutile-to-triton \
  --skill tilegym-monkey-patch-kernels-to-transformers \
  --skill jetson-inference-mem-tune \
  --skill jetson-llm-serve \
  --yes
```

---

### 🔴 Phase 3: RTX 4090 at $10K

**24GB VRAM — serious compute, multi-model capability:**

| Skill | Action | Value |
|-------|--------|-------|
| `jetson-speculative-decoding` | Implement speculative decoding | 2-3× inference latency reduction |
| `tao-run-on-kubernetes` | Containerize and orchestrate | Scale beyond single machine |

**Additional install:**
```bash
npx skills add nvidia/skills \
  --skill jetson-speculative-decoding \
  --skill tao-run-on-kubernetes \
  --yes
```

---

### ⚪ Phase 4: DGX Spark at $15K+

**Maximum capability — defer until hardware arrives:**

| Skill | Action | Value |
|-------|--------|-------|
| `holoscan-setup` | Set up Holoscan for real-time processing | Sensor pipeline acceleration |
| `holoscan-install-container` | Deploy Holoscan in containers | Production deployment |
| `holoscan-install-conda` | Conda-based Holoscan for dev | Faster iteration |
| `tao-run-on-slurm` | Slurm integration | HPC cluster access |
| `tilegym-converting-cutile-to-julia` | Julia conversion (if needed) | Ecosystem bridge |

---

## Architecture Integration Map

```
TSAR Application Layer
├── Python API / CLI
│   ├── [tilegym-monkey-patch] → Accelerated HF transformers
│   └── [jetson-llm-serve] → Model serving endpoint
│
├── Kernel Layer (src/tsar/kernels/)
│   ├── [tilegym-cutile-python] → cuTile kernel implementations
│   ├── [tilegym-adding-cutile-kernel] → New kernel workflow
│   ├── [tilegym-cutile-autotuning] → Per-kernel autotuning
│   ├── [tilegym-improve-cutile-kernel-perf] → Performance optimization
│   └── [tilegym-converting-cutile-to-triton] → Triton conversions
│
├── Inference Pipeline
│   ├── [jetson-inference-mem-tune] → Memory optimization
│   ├── [jetson-llm-benchmark] → Performance measurement
│   └── [jetson-speculative-decoding] → Latency reduction
│
├── Infrastructure Layer
│   ├── [tao-setup-nvidia-gpu-host] → Host GPU setup
│   ├── [tao-run-on-brev] → Cloud GPU access
│   ├── [tao-run-on-kubernetes] → K8s orchestration
│   └── [tao-run-on-slurm] → HPC scheduling
│
└── Optional: Real-time Processing
    ├── [holoscan-setup] → SDK setup
    ├── [holoscan-install-container] → Container deployment
    └── [holoscan-install-conda] → Conda environment
```

---

## Key Recommendations

### 1. Start with cuTile, Not Raw CUDA
cuTile's Python DSL is significantly easier to author and debug than CUDA C, while still generating high-performance code. TSAR's existing CUDA stubs should be **rewritten in cuTile**, not raw CUDA.

### 2. Autotune Everything
The `tilegym-cutile-autotuning` tune-once/cache pattern has zero runtime overhead after first call. Every kernel should use it from day one — retroactively adding autotuning is harder than building it in.

### 3. Benchmark Before and After Every Change
The `jetson-llm-benchmark` JSON output enables automated regression testing. Set up benchmarks before any optimization work begins.

### 4. Use Brev for Pre-Purchase Validation
Before spending $1K/$10K/$15K on hardware, use `tao-run-on-brev` to validate TSAR's performance on target GPU tiers. This de-risks hardware purchases.

### 5. Defer Holoscan Unless Needed
Holoscan is powerful but niche. Only adopt if TSAR develops real-time sensor processing requirements.

### 6. The Monkey-Patch Skill is a Multiplier
`tilegym-monkey-patch-kernels-to-transformers` is the highest-leverage inference skill — it accelerates any HF model without code changes to the model itself.

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| cuTile is new/immature | Triton conversion skill provides escape hatch |
| Skills may change frequently | Run `npx skills update` weekly |
| GPU memory constraints (8GB) | `jetson-inference-mem-tune` + careful model selection |
| Vendor lock-in to NVIDIA | Triton conversion provides portability |
| Skills are instruction sets, not libraries | Agent must follow instructions correctly; validate outputs |

---

## Summary Matrix

| # | Skill | Category | TSAR Priority | Milestone | HW Req |
|---|-------|----------|:---:|-----------|--------|
| 1 | tilegym-cutile-python | GPU Dev | 🔴 Critical | Now | Any NVIDIA GPU |
| 2 | tilegym-adding-cutile-kernel | GPU Dev | 🔴 Critical | Now | Any NVIDIA GPU |
| 3 | tilegym-cutile-autotuning | GPU Dev | 🔴 Critical | Now | Any NVIDIA GPU |
| 4 | tilegym-improve-cutile-kernel-perf | GPU Dev | 🟡 Important | $1K | Ampere+ |
| 5 | tilegym-converting-cutile-to-triton | GPU Dev | 🟡 Important | $1K | Ampere+ |
| 6 | tilegym-converting-cutile-to-julia | GPU Dev | ⚪ Defer | If needed | Any NVIDIA GPU |
| 7 | tilegym-monkey-patch-kernels-to-transformers | GPU Dev | 🟡 Important | $1K | Any NVIDIA GPU |
| 8 | holoscan-install-conda | Infra | ⚪ Defer | $15K+ | Ampere+ |
| 9 | holoscan-install-container | Infra | ⚪ Defer | $15K+ | Ampere+ |
| 10 | holoscan-setup | Infra | ⚪ Defer | $15K+ | Ampere+ |
| 11 | tao-run-on-brev | Infra | 🟢 Useful | Now | Cloud GPU |
| 12 | tao-run-on-kubernetes | Infra | 🟡 Important | $10K | K8s cluster |
| 13 | tao-run-on-slurm | Infra | ⚪ Defer | If needed | Slurm cluster |
| 14 | tao-setup-nvidia-gpu-host | Infra | 🔴 Critical | Now | Any NVIDIA GPU |
| 15 | jetson-inference-mem-tune | Inference | 🟡 Important | $1K | Any NVIDIA GPU |
| 16 | jetson-llm-benchmark | Inference | 🔴 Critical | Now | Any NVIDIA GPU |
| 17 | jetson-llm-serve | Inference | 🟡 Important | $1K | Sufficient VRAM |
| 18 | jetson-speculative-decoding | Inference | 🟡 Important | $10K | 24GB+ VRAM |

---

*Analysis complete. 18 skills evaluated across 4 capital milestones. The cuTile ecosystem (skills 1-5, 7) forms the core GPU development toolkit. Infrastructure skills (8-14) support deployment scaling. Jetson skills (15-18) provide inference optimization patterns.*
