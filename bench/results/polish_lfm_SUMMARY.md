# LFM2.5 polish bench (history sample, M5)

| Model | Load | Mean | p50 | Min–Max | Quality (dictation cleanup) |
|-------|-----:|-----:|----:|---------|-----------------------------|
| **LFM2.5-230M 4bit** | 4.8s | **0.16s** | 0.16s | 0.11–0.27s | Light edits; safe; leaves most stutters |
| **LFM2.5-350M 4bit** | 6.1s | **0.16s** | 0.19s | 0.04–0.41s | More rewrite; often **over-summarizes / drops content** |
| Gemma 3 270M 4bit | 4.9s | 0.47s | 0.55s | — | Hallucinates (unusable) |
| Qwen2.5 0.5B 4bit | 5.7s | 0.35s | 0.35s | — | Mild cleanup, keeps meaning |

Both LFM sizes are **~3× faster** than Qwen0.5B on this Mac for this task.
