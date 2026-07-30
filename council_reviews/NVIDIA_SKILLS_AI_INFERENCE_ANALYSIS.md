# NVIDIA Skills: AI, Inference & Agent Systems Analysis for TSAR

**Analyst:** NVIDIA Skills AI & Inference Analyst  
**Date:** 2026-07-30  
**Context:** Trading Super Agent (TSAR) — DeepSeek-R1 via Ollama + NIM, LiteLLM routing, per-agent model config, circuit breakers  
**Source:** `npx skills add NVIDIA/skills` — [github.com/NVIDIA/skills](https://github.com/NVIDIA/skills)

---

## Executive Summary

NVIDIA's skill catalog contains **35 skills** directly relevant to TSAR's AI/LLM/agent stack across three categories: Agentic AI (22), Training AI (8), and Inference AI (5). The highest-impact skills for TSAR are **dynamo-router-starter** (intelligent LLM request routing), **rag-blueprint** (production RAG for market data), **nemo-relay-*** (agent observability and adaptive tuning), and **nemotron-policy-generator** (trading safety guardrails). These skills are **free Apache-2.0 licensed** and require NVIDIA GPU hardware for self-hosted deployments.

---

## AGENTIC AI SKILLS (22 Skills)

### 1. aiq-deploy

**What it does:** Deploys, validates, troubleshoots, and manages NVIDIA AI-Q Blueprint infrastructure — a multi-agent deep research system with intent classification, shallow/deep researchers, and sandbox execution. Handles Docker Compose, Helm/K8s, and local deployments.

**Why it matters for TSAR:** TSAR's multi-agent architecture (MarketAnalyst, RiskManager, etc.) could leverage AI-Q's deep research capability for fundamental analysis — e.g., researching earnings reports, SEC filings, and market news before generating trading signals. The deployment patterns (compose, helm, health checks) mirror what TSAR needs for production LLM services.

**How to integrate:**
- Deploy AI-Q as a sidecar research service alongside TSAR's main agent loop
- Route fundamental analysis requests (earnings, macro events) through AI-Q's deep researcher
- Use AI-Q's health-check patterns for TSAR's own NIM/Ollama health monitoring

**When to adopt:** Capital Milestone 2 (after basic trading is live) — research capabilities are a value-add, not a blocker.

**Cost:** Free (Apache-2.0). Requires GPU for self-hosted NIM backends. Can use NVIDIA-hosted API endpoints to start.

---

### 2. aiq-research

**What it does:** Calls a running AI-Q backend for routed chat requests and async deep research job lifecycle — polling, report retrieval, streaming, and cancellation. Works with local or self-hosted AI-Q servers.

**Why it matters for TSAR:** Enables TSAR agents to fire off deep research jobs asynchronously (e.g., "research NVDA earnings impact on semiconductor sector") while continuing trading operations. The async job model prevents research from blocking time-critical trading decisions.

**How to integrate:**
- Add `aiq-research` as a tool available to MarketAnalyst and FundamentalAnalyst agents
- Use async research for overnight pre-market preparation
- Stream partial results for real-time event response

**When to adopt:** Capital Milestone 2 — pairs with aiq-deploy.

**Cost:** Free. Requires running AI-Q backend (GPU recommended for NIM models).

---

### 3. i4h-workflow-setup

**What it does:** Sets up Industrial AI workflow infrastructure — primarily for robotics and physical AI pipelines. Provides workflow scaffolding, dataset management, and training pipeline setup.

**Why it matters for TSAR:** Limited direct relevance. The workflow orchestration patterns (pipeline DAGs, dataset versioning) could inform TSAR's data pipeline design for market data ingestion and feature engineering.

**How to integrate:** Reference only — study the workflow patterns for TSAR's data pipeline architecture.

**When to adopt:** Not directly applicable. Use as architectural reference if needed.

**Cost:** Free. No special hardware needed for reference use.

---

### 4. nemo-evaluator-plugin

**What it does:** CLI and SDK for running evaluations against a NeMo Platform server. Supports exact-match, LLM-as-judge, and custom metric evaluation with durable job submission. Runs evaluation specs against models or agents.

**Why it matters for TSAR:** Critical for evaluating TSAR's trading decision quality. Can benchmark DeepSeek-R1's trading signal accuracy, compare model versions, and run regression tests on agent outputs. The LLM-as-judge metric is perfect for evaluating subjective trading reasoning quality.

**How to integrate:**
- Create evaluation specs for trading signal accuracy (entry/exit timing, risk assessment)
- Run LLM-as-judge evaluations on agent reasoning chains
- Use durable jobs for nightly model quality regression testing
- Benchmark before/after model upgrades or prompt changes

**When to adopt:** Capital Milestone 1 — essential for establishing model quality baselines before live trading.

**Cost:** Free. Requires NeMo Platform server (can run locally with Docker). GPU recommended for LLM-as-judge evaluations.

---

### 5. nemo-relay-debug-runtime-integration

**What it does:** Debugs missing events, load failures, and runtime integration issues in NeMo Relay instrumented applications. Diagnoses why lifecycle events aren't firing or middleware isn't executing.

**Why it matters for TSAR:** When TSAR's agent instrumentation breaks (missing traces, silent failures in model calls), this skill provides structured debugging workflows instead of ad-hoc log scanning.

**How to integrate:**
- Use when TSAR agent traces show gaps or missing model call events
- Debug circuit breaker false positives caused by instrumentation issues
- Diagnose middleware chain failures in the agent execution pipeline

**When to adopt:** Capital Milestone 2 — needed when implementing NeMo Relay instrumentation.

**Cost:** Free.

---

### 6. nemo-relay-get-started

**What it does:** Onboarding guide for NeMo Relay — sets up the first instrumented scope, managed execution, and basic lifecycle events in an existing application.

**Why it matters for TSAR:** Entry point for adding observability to TSAR's agent calls. Wraps every LLM call and tool invocation with lifecycle events (start, end, error) for tracing and debugging.

**How to integrate:**
- Start here to instrument TSAR's LiteLLM router calls with NeMo Relay scopes
- Add managed execution wrappers around each agent's model calls
- Enable lifecycle event capture for debugging and performance analysis

**When to adopt:** Capital Milestone 1 — observability should be built in from the start.

**Cost:** Free. Lightweight runtime overhead.

---

### 7. nemo-relay-install

**What it does:** Installation guide for NeMo Relay libraries across Rust, Python, Node.js, and Go runtimes.

**Why it matters for TSAR:** Prerequisite for all NeMo Relay skills. TSAR's Python-based agents need the `nemo_relay` Python package.

**How to integrate:** Install `nemo_relay` Python package in TSAR's environment.

**When to adopt:** Capital Milestone 1.

**Cost:** Free.

---

### 8. nemo-relay-instrument-calls

**What it does:** Wraps existing tool functions and LLM/provider call sites with NeMo Relay scopes and managed execution APIs. Adds lifecycle events, middleware, and guardrails without changing original callable behavior.

**Why it matters for TSAR:** Directly applicable to wrapping TSAR's LiteLLM calls and agent tool invocations. Every model call gets: start event, request intercepts, execution intercepts, response sanitization, and end event — enabling full tracing of the trading decision pipeline.

**How to integration:**
- Wrap `litellm.completion()` calls with `llm.execute()` managed execution
- Wrap agent tool calls (market data fetch, order placement) with `tools.execute()`
- Add conditional execution guardrails (e.g., block trading during circuit breaker trips)

**When to adopt:** Capital Milestone 1 — instrument early for observability.

**Cost:** Free. Negligible runtime overhead.

---

### 9. nemo-relay-instrument-context-isolation

**What it does:** Provides per-request isolation and worker-pool guidance for NeMo Relay instrumented applications. Ensures context doesn't leak between concurrent requests.

**Why it matters for TSAR:** TSAR processes multiple trading signals concurrently. Context isolation prevents one agent's analysis from bleeding into another's — critical for independent signal generation across different instruments/timeframes.

**How to integrate:**
- Apply context isolation to TSAR's concurrent agent execution pool
- Ensure per-request tracing doesn't cross-contaminate between trading pairs

**When to adopt:** Capital Milestone 2 — needed when scaling to concurrent multi-asset trading.

**Cost:** Free.

---

### 10. nemo-relay-instrument-typed-wrappers

**What it does:** Adds type-safe wrappers around NeMo Relay instrumented calls for better IDE support, compile-time safety, and developer ergonomics.

**Why it matters for TSAR:** Improves developer experience when working with TSAR's instrumented agent calls. Type safety catches integration errors early.

**How to integrate:** Apply after initial NeMo Relay instrumentation is complete.

**When to adopt:** Capital Milestone 2 — polish after core instrumentation works.

**Cost:** Free.

---

### 11. nemo-relay-migrate-from-flow

**What it does:** Migrates applications from Flow-style orchestration to NeMo Relay's scope-based instrumentation model.

**Why it matters for TSAR:** If TSAR evolves from a simple sequential agent pipeline to a more complex graph-based workflow, this skill guides the migration path.

**How to integrate:** Reference only — use when TSAR's agent orchestration outgrows sequential flows.

**When to adopt:** Capital Milestone 3+ — only if TSAR's architecture becomes more complex.

**Cost:** Free.

---

### 12. nemo-relay-plugin-adaptive-tuning ⭐ HIGH VALUE

**What it does:** Configures adaptive behavior from runtime signals — improves latency, parallelism, prompt-cache behavior, and model-request behavior. Includes Adaptive Cache Governor (ACG) for prompt cache planning, tool parallelism scheduling, and telemetry-driven tuning.

**Why it matters for TSAR:** **This is one of the most valuable skills for TSAR.** Trading requires ultra-low latency. Adaptive tuning can:
- **Optimize prompt caching** for repeated market analysis patterns (same ticker, similar timeframe)
- **Parallelize tool calls** when an agent needs market data + sentiment + technical indicators simultaneously
- **Auto-tune model request parameters** based on observed latency/quality tradeoffs
- **Learn from runtime signals** which trading scenarios benefit from faster vs. more thorough analysis

**How to integrate:**
- Enable adaptive telemetry with in-memory state on TSAR's agent calls
- Configure ACG for prompt cache optimization on recurring market analysis patterns
- Use tool parallelism scheduling for concurrent data fetching (price + volume + news)
- Measure baseline latency, then iteratively enable adaptive behaviors

**When to adopt:** Capital Milestone 2 — after baseline instrumentation is stable and representative traffic exists.

**Cost:** Free. Requires NeMo Relay instrumentation as prerequisite.

---

### 13. nemo-relay-plugin-build

**What it does:** Builds reusable, configuration-activated NeMo Relay plugins for runtime behavior that can be shared across applications.

**Why it matters for TSAR:** Package TSAR-specific trading behaviors (risk check middleware, market hours guardrails) as reusable Relay plugins.

**How to integrate:** Create TSAR-specific plugins for trading-domain middleware.

**When to adopt:** Capital Milestone 3 — after TSAR's instrumentation patterns stabilize.

**Cost:** Free.

---

### 14. nemo-relay-plugin-observability

**What it does:** Sets up traces, ATIF (Agent Trace Interchange Format), and export configuration for NeMo Relay instrumented applications. Integrates with tracing backends.

**Why it matters for TSAR:** Enables production-grade observability for TSAR's agent pipeline — traces showing every model call, tool invocation, and decision point in the trading flow. Essential for debugging why a trade was made (or wasn't).

**How to integrate:**
- Configure trace export to TSAR's monitoring stack (Prometheus/Grafana or similar)
- Enable ATIF for standardized agent trace interchange
- Set up alerting on anomalous trace patterns (unusually long model calls, high error rates)

**When to adopt:** Capital Milestone 1 — observability from day one.

**Cost:** Free. Requires trace storage backend.

---

### 15. nemo-retriever

**What it does:** CLI tool that indexes documents (PDFs, images, Office, HTML, audio, video) into LanceDB and serves vector search over them. Supports semantic search, verbatim quotes with citation, corpus-level aggregation, and chart/image caption hits.

**Why it matters for TSAR:** Enables RAG over trading-relevant documents — SEC filings, earnings transcripts, research reports, regulatory documents, and market news archives. The multi-format support (PDF, audio for earnings calls, video for analyst presentations) is particularly valuable.

**How to integrate:**
- Index TSAR's knowledge base (historical earnings, SEC filings, trading playbooks) into LanceDB
- Use `retriever query` for context retrieval before generating trading signals
- Support audio ingestion for earnings call transcripts

**When to adopt:** Capital Milestone 2 — when TSAR needs document-grounded trading decisions.

**Cost:** Free. CPU-only for text; GPU recommended for multimedia ingestion.

---

### 16. nemoclaw-user-guide

**What it does:** User guide for NemoClaw — the integration between NeMo and OpenClaw agent framework.

**Why it matters for TSAR:** If TSAR runs on OpenClaw, this skill provides the bridge between NeMo's model serving and OpenClaw's agent orchestration.

**How to integrate:** Reference for OpenClaw-specific NeMo integration patterns.

**When to adopt:** Capital Milestone 1 — if using OpenClaw as TSAR's agent framework.

**Cost:** Free.

---

### 17. nemotron-policy-generator ⭐ HIGH VALUE

**What it does:** Generates custom safety policies for NVIDIA Nemotron content-safety guardrails. Produces Markdown policy, JSON taxonomy, and drop-in inference prompts. Maps rough requirements to structured safety categories. Works with Nemotron-Content-Safety-Reasoning-4B (text) and Nemotron-3-Content-Safety (multimodal).

**Why it matters for TSAR:** **Critical for trading safety.** Can generate guardrail policies for:
- **Position size limits** — "block trades exceeding 5% of portfolio"
- **Risk threshold enforcement** — "block trades when VIX > 30 without human approval"
- **Regulatory compliance** — "no insider trading patterns, no wash trades"
- **Behavioral guardrails** — "never chase losses, always respect stop-losses"
- **Content safety** — ensure agent reasoning doesn't include market manipulation patterns

The structured policy output (Markdown + JSON + system prompt) can be directly injected into TSAR's trading guardrails.

**How to integrate:**
- Generate trading safety policies from TSAR's risk management rules
- Deploy as NeMo Guardrails in front of DeepSeek-R1's trading decisions
- Use the JSON taxonomy for programmatic rule enforcement
- Update policies as trading rules evolve

**When to adopt:** Capital Milestone 1 — safety guardrails must exist before live trading.

**Cost:** Free. Requires Nemotron safety model (can run on NIM or locally with GPU).

---

### 18. nvidia-skill-finder

**What it does:** Discovers and recommends relevant NVIDIA skills based on user intent and project context.

**Why it matters for TSAR:** Helps TSAR's development team find the right NVIDIA skills as requirements evolve.

**How to integrate:** Use during development to discover new relevant skills.

**When to adopt:** Immediately — meta-skill for ongoing discovery.

**Cost:** Free.

---

### 19. rag-blueprint ⭐ HIGH VALUE

**What it does:** Complete NVIDIA RAG Blueprint — deploys, configures, troubleshoots, and manages production RAG systems. Supports Agentic RAG, VLM, guardrails, query rewriting, hybrid search, multi-collection, reranking, reasoning mode, summarization, observability, and MCP integration. Docker Compose and Helm deployments.

**Why it matters for TSAR:** **The most comprehensive RAG solution for TSAR's market intelligence layer.** Key features:
- **Agentic RAG** — planning/execution agent that decomposes complex market queries
- **Hybrid search** — combine semantic search with metadata filters (ticker, date, sector)
- **Multi-collection** — separate collections for earnings, news, research, regulations
- **Query rewriting** — decompose "What's the impact of rising rates on tech valuations?" into sub-queries
- **Reasoning mode** — show the agent's reasoning chain for auditability
- **Reranking** — improve retrieval quality for trading-relevant context
- **VLM support** — process charts, diagrams from research reports

**How to integrate:**
- Deploy RAG Blueprint with Docker Compose alongside TSAR
- Create collections: `earnings_transcripts`, `sec_filings`, `market_news`, `research_reports`
- Configure hybrid search with metadata filters for ticker/date/sector
- Enable Agentic RAG for complex multi-step market research
- Use reasoning mode for audit trail on trading decisions
- Connect to TSAR's agents via the REST API

**When to adopt:** Capital Milestone 2 — core infrastructure for intelligent trading.

**Cost:** Free (Apache-2.0). Requires GPU for self-hosted NIM (embedding, ranking, LLM models). Can use NVIDIA-hosted APIs initially.

---

### 20. rag-eval

**What it does:** Runs RAGAS quality benchmarks on RAG systems — evaluates retrieval quality, answer relevance, faithfulness, and context precision using `corpus/` + `train.json` datasets.

**Why it matters for TSAR:** Quantifies RAG retrieval quality for trading contexts. Can measure whether TSAR's RAG is actually retrieving relevant market information vs. noise.

**How to integrate:**
- Create evaluation datasets from historical trading scenarios
- Run RAGAS benchmarks before/after RAG configuration changes
- Track retrieval quality metrics over time

**When to adopt:** Capital Milestone 2 — after RAG Blueprint is deployed.

**Cost:** Free. Requires NVIDIA_API_KEY for RAGAS judge model.

---

### 21. rag-perf

**What it does:** Latency, throughput, and load testing for RAG systems. Benchmarks end-to-end RAG pipeline performance.

**Why it matters for TSAR:** Trading requires low-latency RAG retrieval. This skill benchmarks whether TSAR's RAG pipeline meets latency requirements for real-time trading decisions.

**How to integrate:**
- Benchmark RAG retrieval latency under trading-relevant load
- Identify bottlenecks in the retrieval → reranking → generation pipeline
- Optimize for sub-second retrieval for time-critical signals

**When to adopt:** Capital Milestone 2 — performance validation before live trading.

**Cost:** Free.

---

### 22. skill-card-generator

**What it does:** Generates skill cards (metadata, descriptions, compatibility info) for NVIDIA skills.

**Why it matters for TSAR:** Useful if TSAR creates custom skills that need to be documented and shared.

**How to integrate:** Use to document TSAR-specific custom skills.

**When to adopt:** Capital Milestone 3 — when TSAR has custom skills to share.

**Cost:** Free.

---

## TRAINING AI SKILLS (8 Skills)

### 23. nemotron-customize ⭐ HIGH VALUE

**What it does:** Plans, configures, and chains Nemotron customization steps into pipelines — curation, translation, SFT/PEFT, pretraining/CPT, RL alignment (DPO/RLVR/GRPO/RLHF), benchmarks, checkpoint conversion, ModelOpt optimization, and evaluation.

**Why it matters for TSAR:** **Enables fine-tuning DeepSeek-R1 or Nemotron models on trading-specific data.** Key capabilities:
- **SFT (Supervised Fine-Tuning)** — train on historical trading decisions and outcomes
- **DPO/GRPO/RLHF** — align models to prefer profitable trading strategies
- **RL alignment** — optimize for trading reward functions (risk-adjusted returns)
- **ModelOpt optimization** — quantize and optimize models for faster inference
- **Evaluation pipelines** — benchmark fine-tuned models against base models

**How to integrate:**
- Curate trading decision datasets (market state → action → outcome)
- Run SFT to teach the model TSAR's trading patterns
- Use GRPO with trading reward functions (Sharpe ratio, max drawdown)
- Optimize with ModelOpt for deployment via NIM/Ollama

**When to adopt:** Capital Milestone 3 — after collecting sufficient trading outcome data.

**Cost:** Free. Requires significant GPU compute for training (A100/H100 recommended).

---

### 24. nemotron-retrieval-recipes

**What it does:** Training recipes for retrieval models — fine-tunes embedding and reranking models for domain-specific retrieval.

**Why it matters for TSAR:** Fine-tune embedding models on financial documents for better retrieval quality in TSAR's RAG pipeline. Domain-specific embeddings significantly outperform general-purpose ones for financial text.

**How to integrate:**
- Fine-tune NV-Embed on TSAR's financial document corpus
- Train custom reranker on trading-relevant relevance judgments
- Deploy fine-tuned models as NIM endpoints

**When to adopt:** Capital Milestone 3 — after RAG Blueprint is deployed and baseline quality is measured.

**Cost:** Free. Requires GPU for training.

---

### 25. nemo-rl-auto-research

**What it does:** Autonomous RL research agent for directed hypothesis testing and open-ended discovery. Guides through the full experiment lifecycle — understanding recipes, wiring RL runs, launching baselines, analyzing results, and using git as research ledger.

**Why it matters for TSAR:** Enables autonomous experimentation with trading strategies using RL. Can systematically test hypotheses like "Does adding sentiment data improve entry timing?" with proper experiment tracking and reproducibility.

**How to integrate:**
- Define trading reward functions (Sharpe, Sortino, max drawdown)
- Create experiment campaigns testing strategy variations
- Use git-branching for experiment tracking and rollback
- Analyze results with structured TSV logs

**When to adopt:** Capital Milestone 3 — requires mature data pipeline and reward function design.

**Cost:** Free. Requires GPU for RL training.

---

### 26. nemo-rl-docs

**What it does:** Documentation reference for NeMo-RL — the reinforcement learning training framework.

**Why it matters for TSAR:** Reference documentation for implementing RL-based trading strategy optimization.

**How to integrate:** Reference for nemo-rl-auto-research and nemo-rl-session-memory.

**When to adopt:** Capital Milestone 3.

**Cost:** Free.

---

### 27. nemo-rl-session-memory

**What it does:** Session memory for NeMo-RL research campaigns — persists experiment state, handoffs, and checkpoint information across sessions.

**Why it matters for TSAR:** Maintains continuity across long-running RL experiment campaigns for trading strategy optimization. Enables resuming experiments after interruptions.

**How to integrate:** Use with nemo-rl-auto-research for persistent experiment tracking.

**When to adopt:** Capital Milestone 3.

**Cost:** Free.

---

### 28. tao-finetune-huggingface-model ⭐ HIGH VALUE

**What it does:** Fine-tunes any HuggingFace CV/VLM/LLM model on local NVIDIA GPUs inside an NGC container. Supports full fine-tuning, LoRA, SFT, DPO, GRPO. Six-step workflow: inspect, hardware setup, research, generate, train+eval, push to Hub.

**Why it matters for TSAR:** **Directly applicable to fine-tuning DeepSeek-R1 or other models on trading data.** Key features:
- **LoRA fine-tuning** — efficiently adapt large models with minimal compute
- **DPO/GRPO** — align models to prefer profitable trading patterns
- **Push to Hub** — share fine-tuned models across TSAR deployments
- **Reproducible pipelines** — emit self-contained rerun skills for training runs

**How to integrate:**
- Create trading instruction datasets (market analysis → trading decision)
- Fine-tune DeepSeek-R1 with LoRA on TSAR's historical trading data
- Use DPO to align toward risk-adjusted return optimization
- Push fine-tuned models to HuggingFace Hub for deployment

**When to adopt:** Capital Milestone 3 — after collecting sufficient labeled trading data.

**Cost:** Free. Requires NVIDIA GPU with ≥24GB VRAM for ≤3B models (A100/H100 for larger models).

---

### 29. tao-run-automl

**What it does:** Runs AutoML workflows — automated hyperparameter search, architecture selection, and training optimization for AI models.

**Why it matters for TSAR:** Automate the search for optimal model configurations for trading tasks — finding the best LoRA rank, learning rate, or training data mix.

**How to integrate:** Use to optimize fine-tuning hyperparameters for trading models.

**When to adopt:** Capital Milestone 3 — after initial fine-tuning experiments.

**Cost:** Free. Requires GPU compute.

---

### 30. data-designer

**What it does:** Creates synthetic datasets and data generation pipelines. Supports structured output schemas, custom generators, LLM judges for quality scoring, and Jinja2 templates for prompt construction.

**Why it matters for TSAR:** **Generate synthetic training data for trading scenarios.** Can create:
- Synthetic market scenarios with known optimal actions
- Edge case trading situations (flash crashes, circuit breakers, gaps)
- Augmented training data from limited historical examples
- Quality-scored datasets using LLM judges

**How to integrate:**
- Define trading scenario schemas (market state, indicators, optimal action)
- Generate synthetic training data for rare market events
- Use LLM judges to score synthetic data quality
- Feed synthetic data into fine-tuning pipelines

**When to adopt:** Capital Milestone 2 — synthetic data generation is valuable even before fine-tuning.

**Cost:** Free. GPU recommended for LLM-based generation.

---

## INFERENCE AI SKILLS (5 Skills)

### 31. dynamo-interconnect-check

**What it does:** Validates interconnect topology and performance for NVIDIA Dynamo inference deployments — checks NVLink, InfiniBand, and network connectivity between GPU nodes.

**Why it matters for TSAR:** Ensures TSAR's inference infrastructure has optimal GPU-to-GPU communication for distributed model serving. Poor interconnect = higher inference latency.

**How to integrate:** Run before deploying multi-GPU inference setups for TSAR.

**When to adopt:** Capital Milestone 2 — when scaling to multi-GPU inference.

**Cost:** Free. Requires multi-GPU hardware.

---

### 32. dynamo-recipe-runner

**What it does:** Selects, validates, patches, and deploys NVIDIA Dynamo Kubernetes recipes for LLM inference. Handles model/backend/GPU selection, manifest patching, and deployment with smoke testing.

**Why it matters for TSAR:** **Production-grade LLM deployment on Kubernetes.** Provides validated deployment recipes for various models (including Qwen, Llama) with vLLM, SGLang, or TensorRT-LLM backends. This is how TSAR would deploy models at scale.

**How to integrate:**
- Select recipes matching TSAR's model (DeepSeek-R1) and hardware
- Patch manifests for TSAR's specific GPU type and count
- Deploy to TSAR's Kubernetes cluster
- Smoke test with OpenAI-compatible endpoints

**When to adopt:** Capital Milestone 2 — when moving from single-node Ollama to production Kubernetes deployment.

**Cost:** Free. Requires Kubernetes cluster with GPU nodes.

---

### 33. dynamo-router-starter ⭐ HIGH VALUE

**What it does:** Starts and configures Dynamo router modes — round-robin, KV-aware, least-loaded, device-aware-weighted, direct, and random routing. Includes smoke testing and mode comparison.

**Why it matters for TSAR:** **Directly replaces/enhances TSAR's LiteLLM routing with NVIDIA's intelligent LLM router.** Key benefits:
- **KV-aware routing** — routes requests to workers with warm KV cache for the same prefix, dramatically reducing time-to-first-token for repeated market analysis patterns
- **Least-loaded routing** — distributes requests to the least busy worker for optimal throughput
- **Device-aware routing** — routes based on GPU utilization, not just request count
- **Smoke testing** — validates routing health before live traffic

For TSAR specifically:
- KV-aware routing is huge — market analysis for the same ticker/timeframe shares prompt prefixes, so KV cache reuse = faster responses
- Least-loaded routing prevents overload during high-volatility periods when multiple agents need simultaneous inference

**How to integrate:**
- Replace LiteLLM's simple round-robin with Dynamo's KV-aware routing
- Deploy Dynamo frontend as TSAR's model gateway
- Configure KV routing for recurring market analysis patterns
- Use device-aware routing for multi-GPU TSAR deployments
- Benchmark round-robin vs KV routing with TSAR's actual prompt patterns

**When to adopt:** Capital Milestone 2 — significant latency improvement over basic routing.

**Cost:** Free. Requires Python 3.10+ and deployed Dynamo workers.

---

### 34. dynamo-troubleshoot

**What it does:** Diagnoses and resolves Dynamo deployment failures — worker crashes, model loading errors, routing issues, and connectivity problems.

**Why it matters for TSAR:** Production troubleshooting guide for TSAR's Dynamo-based inference infrastructure.

**How to integrate:** Reference for production incident response.

**When to adopt:** Capital Milestone 2 — with Dynamo deployment.

**Cost:** Free.

---

### 35. tao-run-inference-service

**What it does:** Deploys optimized inference services for TAO-trained models — handles TensorRT optimization, serving configuration, and endpoint management.

**Why it matters for TSAR:** Deploy fine-tuned trading models as optimized inference services with TensorRT acceleration for maximum throughput.

**How to integrate:**
- Optimize fine-tuned trading models with TensorRT
- Deploy as inference endpoints for TSAR's agent pipeline
- Benchmark against unoptimized serving

**When to adopt:** Capital Milestone 3 — after fine-tuning produces production-ready models.

**Cost:** Free. Requires NVIDIA GPU.

---

## PRIORITY MATRIX FOR TSAR

### Tier 1 — Implement at Capital Milestone 1 (Immediate)
| Skill | Impact | Effort | Why |
|-------|--------|--------|-----|
| nemo-relay-get-started | High | Low | Observability from day one |
| nemo-relay-instrument-calls | High | Low | Trace every LLM call |
| nemo-relay-plugin-observability | High | Low | Production monitoring |
| nemotron-policy-generator | Critical | Medium | Trading safety guardrails |
| nemo-evaluator-plugin | High | Medium | Model quality baselines |
| nvidia-skill-finder | Low | None | Meta-skill for discovery |

### Tier 2 — Implement at Capital Milestone 2 (After Basic Trading)
| Skill | Impact | Effort | Why |
|-------|--------|--------|-----|
| dynamo-router-starter | Critical | Medium | Intelligent LLM routing (KV-aware) |
| rag-blueprint | Critical | High | Market intelligence RAG |
| rag-eval | High | Low | RAG quality measurement |
| rag-perf | High | Low | RAG latency benchmarking |
| nemo-retriever | High | Medium | Document retrieval |
| nemo-relay-plugin-adaptive-tuning | High | Medium | Latency optimization |
| dynamo-recipe-runner | High | Medium | Production model deployment |
| dynamo-troubleshoot | Medium | Low | Incident response |
| data-designer | Medium | Medium | Synthetic training data |
| nemo-relay-instrument-context-isolation | Medium | Low | Concurrent agent isolation |

### Tier 3 — Implement at Capital Milestone 3 (Strategy Optimization)
| Skill | Impact | Effort | Why |
|-------|--------|--------|-----|
| nemotron-customize | Critical | High | Fine-tune trading models |
| tao-finetune-huggingface-model | High | High | LoRA/DPO on trading data |
| nemotron-retrieval-recipes | High | High | Domain-specific embeddings |
| nemo-rl-auto-research | High | High | RL strategy optimization |
| tao-run-inference-service | Medium | Medium | Optimized model serving |
| tao-run-automl | Medium | Medium | Hyperparameter optimization |
| nemo-relay-plugin-build | Low | Low | Reusable plugins |
| nemo-relay-migrate-from-flow | Low | Low | Architecture evolution |

### Not Directly Applicable
| Skill | Reason |
|-------|--------|
| i4h-workflow-setup | Robotics/physical AI focused |
| nemo-rl-docs | Reference only (use with nemo-rl-auto-research) |
| nemo-rl-session-memory | Use with nemo-rl-auto-research |
| dynamo-interconnect-check | Multi-node GPU only |
| skill-card-generator | Meta-tool for skill documentation |
| nemoclaw-user-guide | OpenClaw-specific reference |

---

## COST ANALYSIS

### Software Costs
- **All skills:** Free (Apache-2.0 license)
- **NVIDIA NIM:** Free self-hosted; pay-per-use on NVIDIA API catalog
- **NeMo Platform:** Free open-source components

### Hardware Requirements
| Component | Minimum | Recommended | Cost (Cloud) |
|-----------|---------|-------------|--------------|
| Inference GPU | 1x RTX 4090 (24GB) | 1x A100 (80GB) | ~$1-3/hr |
| Training GPU | 1x A100 (40GB) | 4x H100 (80GB) | ~$2-12/hr |
| RAG Storage | 100GB SSD | 500GB NVMe | ~$10-50/mo |
| Kubernetes | 3-node CPU | GPU node pool | ~$200-2000/mo |

### Recommended TSAR GPU Allocation
- **Inference (Ollama/NIM):** 1-2x A100 80GB for DeepSeek-R1 serving
- **RAG (embeddings/reranking):** 1x A100 40GB or T4 for lighter models
- **Training (fine-tuning):** 2-4x A100/H100 (on-demand, not always-on)
- **Total estimated:** $500-2000/mo for cloud; one-time $10K-50K for on-prem

---

## INTEGRATION ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────┐
│                        TSAR Agent Layer                         │
│  MarketAnalyst │ RiskManager │ ExecutionAgent │ ResearchAgent   │
└────────┬───────┴──────┬──────┴───────┬────────┴───────┬─────────┘
         │              │              │                │
    ┌────▼──────────────▼──────────────▼────────────────▼────┐
    │              NeMo Relay Instrumentation                 │
    │  (nemo-relay-instrument-calls + adaptive-tuning)       │
    └────────┬──────────────┬──────────────┬─────────────────┘
             │              │              │
    ┌────────▼──────┐ ┌─────▼──────┐ ┌────▼──────────────┐
    │ Dynamo Router  │ │ RAG Blueprint│ │ NeMo Guardrails  │
    │ (KV-aware)    │ │ (Agentic RAG)│ │ (Policy Generator│
    └────────┬──────┘ └─────┬──────┘ └────┬──────────────┘
             │              │              │
    ┌────────▼──────────────▼──────────────▼─────────────────┐
    │              Model Serving Layer                         │
    │  Ollama (dev) │ NIM (prod) │ Dynamo (scale)           │
    │  DeepSeek-R1  │ Nemotron   │ Fine-tuned models        │
    └────────────────────────────────────────────────────────┘
```

---

## KEY RECOMMENDATIONS

1. **Start with observability** — Install NeMo Relay instrumentation immediately. You can't improve what you can't measure. Every LLM call should be traced.

2. **Safety before trading** — Use nemotron-policy-generator to create trading guardrails before any live trading. This is non-negotiable.

3. **Dynamo Router > LiteLLM for production** — KV-aware routing is a game-changer for TSAR's recurring market analysis patterns. Migrate from LiteLLM to Dynamo when scaling.

4. **RAG Blueprint for market intelligence** — The Agentic RAG with hybrid search and multi-collection support is purpose-built for the kind of document-heavy research TSAR needs.

5. **Fine-tune later, not never** — After collecting 3-6 months of trading outcomes, use nemotron-customize + tao-finetune-huggingface-model to create trading-specific models.

6. **Synthetic data bridges the gap** — Use data-designer to generate training data for rare market events before they happen in production.

7. **Adaptive tuning compounds** — Once you have representative traffic patterns, nemo-relay-plugin-adaptive-tuning continuously optimizes latency and cache behavior without manual intervention.

---

## NEXT STEPS

1. [ ] Install nemo-relay-get-started + nemo-relay-instrument-calls in TSAR dev environment
2. [ ] Run nemotron-policy-generator to create initial trading safety policies
3. [ ] Deploy RAG Blueprint with Docker Compose for market data ingestion
4. [ ] Benchmark Dynamo router-starter KV-aware routing vs current LiteLLM setup
5. [ ] Create evaluation dataset and run rag-eval baseline
6. [ ] Set up nemo-evaluator-plugin for trading signal quality measurement
