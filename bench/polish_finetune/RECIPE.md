# Dictation polish fine-tune recipe (LFM2.5 on Mac)

Target: **LiquidAI LFM2.5-350M** (or 230M) via **MLX LoRA** on Apple Silicon.  
Goal: raw ASR text → cleaned dictation text (no summary, no refusals).

## 1. Data schema

Each training row is chat JSONL (`messages`):

```json
{
  "messages": [
    {
      "role": "system",
      "content": "Clean this voice dictation for typing into an app. Keep every idea; remove stutters and fillers; fix light grammar. Output only the cleaned text."
    },
    { "role": "user", "content": "<raw ASR / messy spoken text>" },
    { "role": "assistant", "content": "<clean written text>" }
  ]
}
```

Files mlx-lm expects in a directory:

- `train.jsonl`
- `valid.jsonl`
- optional `test.jsonl`

## 2. Mix (recommended)

| Source | Share | Purpose |
|--------|------:|---------|
| **Synthetic spoken mess → clean** | ~60% | Volume: stutters, fillers, false starts |
| **Public cleanup pairs** (if available) | ~25% | Real STT noise patterns |
| **Your MacWispr history** (hand-fixed or teacher-cleaned) | ~15% | Domain match (product UI, model names, your style) |

Start small for a smoke train: **~500–2k pairs**.  
Solid first adapter: **5k–20k pairs**.  
Production-grade: **50k+** + iterative human review.

## 3. Synthetic rules (messy from clean)

From a clean sentence, randomly apply 1–4 of:

1. **Fillers:** insert `um`, `uh`, `like`, `you know`, `I mean`, `basically`
2. **Repeats:** `that` → `that that that`
3. **False starts:** `We should use Qwen` → `We should use, wait, we should use Qwen`
4. **Spoken numbers:** `0.6B` → `zero point six B`
5. **Missing caps / broken punct:** lowercase starts, `what ?`, trailing commas
6. **ASR-ish typos:** Parakeet→Parquet, Qwen→Quen (sparse)

Target must stay the original clean text (no shortening).

## 4. Quality filters

Drop pairs if:

- clean empty or raw empty  
- clean is **&lt; 40%** of raw word count (over-summary teacher)  
- clean is **&gt; 2.5×** raw (hallucination)  
- assistant contains “I'm sorry” / “as an AI”

## 5. Train (this repo)

```bash
cd bench
source .venv-polish/bin/activate

# Build data
python polish_finetune/prepare_data.py

# LoRA on LFM2.5-350M (~minutes–hours depending on iters)
python polish_finetune/train_mlx.sh
```

Defaults (M5 / 32GB class):

| Setting | Value | Why |
|---------|------:|-----|
| Model | `LiquidAI/LFM2.5-350M-MLX-4bit` | Small + fast; was over-aggressive base |
| Type | LoRA | Fits RAM; quick iterate |
| Batch | 2–4 | Unified memory headroom |
| Iters | 200–600 smoke / 2000+ real | See time table |
| LR | 1e-5 – 2e-5 | Small models overfit fast |
| Max seq | 512–1024 | Dictation paragraphs |
| `--mask-prompt` | on | Loss only on assistant tokens |

## 6. Time estimates (Apple M5, 32GB, LFM2.5-350M LoRA 4-bit)

| Scale | Pairs | Iters (batch≈2) | Wall clock (order of) |
|-------|------:|----------------:|----------------------|
| Smoke | 500 | 200 | **~5–15 min** |
| First useful adapter | 2–5k | 800–1500 | **~30–90 min** |
| Stronger | 10–20k | 2000–4000 | **~2–6 hours** |
| Full day run | 50k+ | 5k–10k | **~half day** |

230M is typically **~1.3–1.5× faster** than 350M.  
Full fine-tune (not LoRA) is slower and needs more memory — skip on first pass.

## 7. Eval

Hold out your real history clips:

```bash
python polish_finetune/eval_adapter.py \
  --model LiquidAI/LFM2.5-350M-MLX-4bit \
  --adapter polish_finetune/adapters/lfm350-polish
```

Compare: raw vs base LFM vs adapter (latency + over-short rate + side-by-side).

## 8. Deploy into MacWispr (later)

1. Fuse adapter → MLX weights (`mlx_lm.fuse`) or load base+adapter at runtime  
2. Wire as polish provider next to Qwen CoreML  
3. Keep **flow** system prompt aligned with training system string  

## 9. Two product modes (separate adapters)

| Mode | Adapter | Behavior | Default? |
|------|---------|----------|----------|
| **Light polish** | `adapters/lfm350-polish-teacher` | Grammar, stutters, caps — keep wording | Safer default |
| **Smart / course-correction** | `adapters/lfm350-smart-course` | Honors “no not X, Y” self-repairs (bag→phone) | **Opt-in** |

Prompts: `data/prompts.json` (`light` vs `smart`).  
Build both datasets: `python polish_finetune/build_dual_datasets.py`  
Train smart: `DATA=polish_finetune/data/smart ADAPTER=.../lfm350-smart-course ITERS=600 ./polish_finetune/train_mlx.sh`

Teacher sources: Grok-cleaned MacWispr history + subagent synthetic course-correction pairs.

## 10. License notes

- LFM: Liquid open weights — check [Liquid license](https://huggingface.co/LiquidAI) for distribution  
- Switchboard-class data is often **LDC licensed** (not free to ship raw)  
- Prefer synthetic + your history + explicitly open HF sets for a shippable app
