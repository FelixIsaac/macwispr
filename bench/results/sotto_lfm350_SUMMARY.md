# Sotto LFM2.5-350M cleanup bench (M5)

**Model:** `juanquivilla/sotto-cleanup-lfm25-350m-mlx-5bit` (MIT)  
**Prompt:** their production format `### Input:\n...\n\n### Output:\n`  
**Date:** 2026-07-12  

## Data source (Sotto)

**Mostly synthetic**, not human transcripts:

1. Programmatic corruption of clean public text  
2. LLM-generated pairs (Qwen / Grok)  
3. Small hand-crafted edge cases  

~124k train pairs · MIT · tags: `synthetic-data`

## Their published scores (model card)

| Metric | soup_30 |
|--------|--------:|
| Number accuracy (171 val) | **96.5%** |
| 66-case adversarial (greedy) | **86.4%** |
| Filler-free on 241 long | 71.8% |
| Sub-deletion >15% (long) | **5.0%** |

Their evals are **private/custom** (not public GEC/LibriSpeech polish boards).

## Our re-run

### On **our** history bench (10 MacWispr clips)

| Model | Mean latency | Over-short (&lt;40% words) |
|-------|-------------:|--------------------------:|
| Base LFM 350M (prior) | ~66 ms | **8/10** (collapses) |
| Our LC-350M-light | ~166 ms | **1/10** |
| Our LC-350M-smart | ~79 ms | 5/10 |
| **Sotto MLX 5-bit** | **~250 ms** | **0/10** |

Sotto keeps long product rants; light fixes (caps, some stutters). Not aggressive rewrite.

### Course-correction (8 phrases, our style)

| Raw | Sotto out |
|-----|-----------|
| bag no not bag my phone | keeps “bag… Not not not bag my phone” (weak) |
| Qwen wait no Parakeet | partial (keeps both) |
| keys top no bottom | **Put the keys at the bottom collapsed.** |
| Slack wait no email | **Email instead.** |
| Tuesday no Wednesday | **Meet on Wednesday at 3:00.** |
| 1.2B no 350M | **Use the 350M model.** |
| milk no not milk eggs | **Buy eggs.** |
| open main wait no branch | **Open a branch.** |

≈ **5–6/8** clear final-intent hits (similar ballpark to our smart adapter; bag/Qwen harder).

### On **their** validation slice (n=50, not full 6.9k)

| Metric | Value |
|--------|------:|
| Exact match | **50%** |
| Normalized match | **64%** |
| Mean latency | **~51 ms** |
| Over-short | 1/50 |

(Full val would be better for a fair “Sotto score”; n=50 is a smoke check.)

## Bench map: ours vs his

| Bench | What | Comparable? |
|-------|------|-------------|
| Ours: `polish_history_sample` | Real MacWispr mess, latency + over-short | Yes — run any model here |
| Ours: course-correction seeds | Self-repairs | Yes |
| Ours: LibriSpeech WER | **ASR only**, not polish | No |
| His: number accuracy / adversarial / filler-long | Synthetic domain, their labels | Only if we re-implement their scorers |
| His: train/val dataset | Gold input→output | Yes — score exact/norm match |

**No shared public polish leaderboard.** Fair compare = same set of inputs.

## Takeaway

- **Sotto model is real, trained, MIT, strong baseline** for Mac dictation polish.  
- Data is **synthetic + hand edges**, not human-labeled podcasts.  
- On **our history**: best keep-all so far (**0/10** over-short).  
- On **course-correction**: competitive with our smart LoRA.  
- Latency on long history ~**0.15–0.4s** — still fine for polish-after-STT.  
- Raw JSON: `sotto_lfm350_bench.json`
