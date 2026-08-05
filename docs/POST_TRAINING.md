# Post-Training Inside the Harness

> "You can now also improve the AI model, the large language model, inside the harness. That's a capability that's never existed before."
> — Jensen Huang, NVIDIA CEO

## Overview

The TSAR post-training pipeline implements **learning from experience** — the LLM that powers trading decisions gets fine-tuned on every trade the system makes. This closes the self-improvement loop:

```
TRADE → OBSERVE → REFLECT → EXTRACT → ADAPT → FINE-TUNE → BETTER TRADE
```

The flywheel now has 5 steps instead of 4:

| Step | Component | What it does |
|------|-----------|--------------|
| 1. EXTRACT | ShadowExtractor | Extract rules from trade history |
| 2. VALIDATE | RuleValidator | Backtest rules against OHLCV data |
| 3. MUTATE | GenomeMutator | Propose strategy parameter changes |
| 4. EVOLVE | StrategyGeneticist | Apply accepted mutations |
| **5. FINE-TUNE** | **PostTrainingPipeline** | **Fine-tune LLM from trade data** |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Flywheel Orchestrator                      │
│                                                               │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐  │
│  │ EXTRACT  │──▶│ VALIDATE │──▶│  MUTATE  │──▶│  EVOLVE  │  │
│  │ (Rules)  │   │ (OHLCV)  │   │ (Params) │   │ (Apply)  │  │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘  │
│       │                                              │       │
│       │         ┌─────────────────────────┐          │       │
│       └────────▶│   POST-TRAINING         │◀─────────┘       │
│                 │                         │                   │
│                 │  ┌─────────┐            │                   │
│                 │  │GENERATE │ Training   │                   │
│                 │  │Dataset  │ Examples   │                   │
│                 │  └────┬────┘            │                   │
│                 │       │                 │                   │
│                 │  ┌────▼────┐            │                   │
│                 │  │ TRAIN   │ LoRA/QLoRA │                   │
│                 │  │ (LoRA)  │ Fine-tune  │                   │
│                 │  └────┬────┘            │                   │
│                 │       │                 │                   │
│                 │  ┌────▼────┐            │                   │
│                 │  │EVALUATE │ vs Base    │                   │
│                 │  │ Model   │ Model      │                   │
│                 │  └────┬────┘            │                   │
│                 │       │                 │                   │
│                 │  ┌────▼────┐            │                   │
│                 │  │ DEPLOY  │ If Better  │                   │
│                 │  │ Adapter │            │                   │
│                 │  └─────────┘            │                   │
│                 └─────────────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
```

## Components

### TradeDatasetGenerator

Converts the system's accumulated knowledge into training data:

**Source Data:**
- `TradeMemory` — Every closed trade with its reflection
- `LessonArchive` — Distilled trading wisdom (critical/high severity)
- `PatternLibrary` — Validated market patterns with statistics

**Training Example Types:**

1. **Trade Reflection** — "Given this market context, what's the optimal action?"
   - Response based on actual outcome + post-trade reflection
   - Includes counterfactual examples from losing trades

2. **Lesson Application** — "Given this situation, what principle applies?"
   - Response from the lesson archive with violation history

3. **Pattern Recognition** — "Given these indicators, what pattern do you see?"
   - Response includes statistical profile and trading recommendation

**Format:**
```json
{
  "instruction": "Analyze the following trading setup for BTC/USDT:\n- Strategy: momentum\n- Direction: BUY\n- Market regime: trending_bull\n- Signal confidence: 0.82\n...",
  "response": "Yes, execute the BUY trade. This setup has a favorable risk/reward profile...\n\nStrengths: ...\nKey insight: ...\nSuggested targets: Entry at 65000, take profit near 68000.",
  "system_prompt": "You are TSAR, an expert cryptocurrency trading analyst..."
}
```

### LoRATrainer

Fine-tunes the base model using LoRA (Low-Rank Adaptation):

- **QLoRA support** — 4-bit quantized training for memory efficiency
- **Configurable LoRA rank** — Default: 16 (higher = more expressive)
- **Target modules** — Attention + MLP projection layers
- **Checkpointing** — Saves adapter after each epoch

**Dependencies (optional):**
```bash
pip install torch peft transformers trl datasets
```

### PostTrainingEvaluator

Compares fine-tuned vs base model on held-out test scenarios:

| Dimension | Weight | What it measures |
|-----------|--------|-----------------|
| Directional accuracy | 35% | Correct buy/sell/hold recommendations |
| Risk awareness | 25% | Mentions of stop loss, position sizing |
| Lesson adherence | 25% | Applies known trading principles |
| Response quality | 15% | Coherence, specificity, actionability |

**Acceptance criteria:**
- Overall improvement ≥ 5%
- No dimension regresses by > 3%
- At least 2 of 4 dimensions improve

### PostTrainingPipeline

Orchestrates the full cycle: GENERATE → TRAIN → EVALUATE → DEPLOY

## Configuration

All settings in `config/finetune_config.yaml`:

```yaml
# LoRA parameters
lora:
  rank: 16           # Low-rank dimension
  alpha: 32          # Scaling factor (typically 2x rank)
  dropout: 0.05      # Regularization
  use_qlora: true    # 4-bit quantized training

# Training hyperparameters
training:
  epochs: 3
  batch_size: 4
  learning_rate: 2.0e-4
  warmup_ratio: 0.1
  lr_scheduler: "cosine"

# Pipeline triggers
triggers:
  auto_trigger: true
  min_trades_between_runs: 50
  cooldown_hours: 6
  max_runs_per_day: 2
```

## Flywheel Integration

The post-training pipeline is wired into the `FlywheelOrchestrator`:

```python
# In flywheel_orchestrator.py:
class FlywheelOrchestrator:
    POST_TRAINING_BATCH_SIZE = 50  # Run every 50 trades
    POST_TRAINING_COOLDOWN_S = 21600  # 6-hour cooldown

    async def _run_flywheel(self):
        # Steps 1-4: EXTRACT → VALIDATE → MUTATE → EVOLVE
        ...

        # Step 5: FINE-TUNE (if conditions met)
        await self._maybe_run_post_training(run_id)
```

**Triggers:**
- After every 50 new closed trades
- With at least 6 hours since last run
- Maximum 2 runs per day (safety guard)

## Usage

### Automatic (via Flywheel)

The pipeline runs automatically as part of the flywheel. No manual intervention needed.

### Manual Trigger

```python
from src.llm.post_training import PostTrainingPipeline

pipeline = PostTrainingPipeline(
    trade_memory=trade_memory,
    lesson_archive=lesson_archive,
    pattern_library=pattern_library,
    config=finetune_config,
)

result = pipeline.run()
if result["status"] == "deployed":
    print(f"New model deployed: {result['adapter_path']}")
    print(f"Improvement: {result['improvement_pct']:.1f}%")
```

### Dataset Generation Only

```python
from src.llm.post_training import TradeDatasetGenerator

generator = TradeDatasetGenerator(trade_memory, lesson_archive, pattern_library)
examples = generator.generate(min_trades=20)
stats = generator.compute_stats(examples)

print(f"Generated {stats.total_examples} examples")
print(f"  - {stats.win_examples} win examples")
print(f"  - {stats.loss_examples} loss examples")
print(f"  - {stats.lesson_examples} lesson examples")
print(f"  - {stats.pattern_examples} pattern examples")

generator.save_dataset(examples, "data/datasets/trade_v1.jsonl")
```

### Training Only

```python
from src.llm.post_training import LoRATrainer

trainer = LoRATrainer(config=finetune_config)
run = trainer.train(dataset_path="data/datasets/trade_v1.jsonl")

print(f"Training loss: {run.training_loss:.4f}")
print(f"Adapter saved to: {run.adapter_path}")
```

### Evaluation Only

```python
from src.llm.post_training import PostTrainingEvaluator

evaluator = PostTrainingEvaluator(config=finetune_config)
result = evaluator.evaluate(
    base_model="Qwen/Qwen2.5-7B-Instruct",
    adapter_path="data/models/run123/adapter",
    trade_memory=trade_memory,
)

print(f"Improvement: {result.improvement_pct:.1f}%")
print(f"Accepted: {result.accepted}")
```

## Output Structure

```
data/
├── datasets/
│   ├── trade_dataset_20260805_120000.jsonl   # Training data
│   └── trade_dataset_20260806_180000.jsonl
└── models/
    ├── deployments.jsonl                      # Deployment history
    ├── a1b2c3d4e5f6/
    │   └── adapter/                           # LoRA adapter
    │       ├── adapter_config.json
    │       ├── adapter_model.safetensors
    │       └── tokenizer.json
    └── f6e5d4c3b2a1/
        └── adapter/
            └── ...
```

## Safety Guards

- **Budget enforcement** — LLM calls respect daily/monthly limits
- **Cooldown periods** — Prevents runaway training loops
- **Regression detection** — Rejects models that perform worse
- **Deployment rollback** — Keeps previous adapters for rollback
- **Max runs per day** — Hard limit on training frequency
- **Graceful degradation** — Works without GPU/training deps

## Dependencies

All optional — the system works without them (just skips fine-tuning):

| Package | Purpose | Required for |
|---------|---------|-------------|
| `torch` | PyTorch | Training |
| `peft` | LoRA adapters | Training |
| `transformers` | Model loading | Training + Eval |
| `trl` | SFTTrainer | Training |
| `datasets` | HuggingFace datasets | Training |
| `bitsandbytes` | QLoRA quantization | 4-bit training |

## Jensen's Vision Realized

This pipeline implements exactly what Jensen described:

1. **"Improve the AI model"** — LoRA fine-tuning on trade data
2. **"Inside the harness"** — Integrated into the existing flywheel
3. **"Never existed before"** — The model learns from every trade automatically

The LLM that makes trading decisions gets better at making trading decisions by learning from every decision it (and the system) makes. This is the missing piece that turns TSAR from a static AI system into a self-improving one.
