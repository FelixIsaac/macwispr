# Polish model bench (your MacWispr history)

**Machine:** Apple M5 · 32 GB RAM  
**Data:** 12 real history transcripts (`bench/data/polish_history_sample.json`)  
**Task:** dictation cleanup (grammar, stutters, light structure)  
**Date:** 2026-07-12  

## Latency (post-warmup, generate only)

| Model | Load | Warmup | Mean | p50 | Min | Max |
|-------|-----:|-------:|-----:|----:|----:|----:|
| **Gemma 3 270M-it 4bit** (`mlx-community/gemma-3-270m-it-4bit`) | 4.86s | 1.28s | **0.47s** | 0.55s | 0.14s | 0.79s |
| **Qwen2.5 0.5B-Instruct 4bit** | 5.71s | 0.58s | **0.35s** | 0.35s | 0.25s | 0.56s |
| Rule-based only (app `postProcess`) | — | — | **≪1ms** | — | — | — |

Hardware path: **MLX on Apple Silicon GPU** (this Mac’s M5).

## Quality (subjective, this set)

| Model | Usable for polish? | Notes |
|-------|--------------------|--------|
| **Rule-based** | Barely | Almost no change; leaves stutters (`as a as a`, `that that that`) |
| **Gemma 3 270M** | **No** | Fast but **does not follow** cleanup instructions: invents meta-text, loops, drops meaning, sometimes unrelated scripts |
| **Qwen2.5 0.5B** | **Partially** | Keeps meaning; light fixes (caps, some stutter removal). Still leaves many spoken artifacts |

### Example (sample 1)

**Raw:**  
`…use that as a as a baseline… which which model… Gemma three two seventy M… that that that way it's much more better.`

**Gemma 270M:** hallucinated unrelated “I am a careful editor…” boilerplate — **failed**.

**Qwen 0.5B:**  
`…use that as a baseline… which model… Gemma three, two, seventy M… That way it's much more better.` — mild cleanup, still imperfect.

## Takeaway

1. **Base Gemma 3 270M is too small / poorly aligned for free-form polish** out of the box — latency is fine (~0.5s), quality is not.  
2. **Fine-tuning 270M on (raw → clean) pairs** could help; base model alone is not shippable for MacWispr polish.  
3. **Qwen ~0.5–0.6B** is a better default base (matches what the app already targets with CoreML polish).  
4. For Flow-level rewrites you’ll want a stronger model, a fine-tune, or cloud BYOK — not stock 270M.

## Artifacts

- `polish_gemma270m.json` — full Gemma runs  
- `polish_qwen05b.json` — full Qwen runs  
- Re-run: `bench/.venv-polish/bin/python bench/bench_polish.py`
