> ⚠️ **CONTAMINATED — DO NOT TRUST.** The 8 "course" phrases below are
> `COURSE_PAIRS[0:8]` from `build_sotto_ft_data.py`, i.e. verbatim training
> rows. The 8/8 is memorization, not generalization. Superseded by the
> leak-free run in **`sotto_holdout_clean_SUMMARY.md`** (real result: 10→13/16).

# Sotto base vs Sotto+our LoRA

**Train:** 230 unique concepts → 716 rows · 600 iters · LR 5e-6 · LoRA on `sotto-cleanup-lfm25-350m-mlx-5bit`  
**Adapter:** `bench/polish_finetune/adapters/sotto-lc-ft`  
**Same tests:** 10 MacWispr history + 8 course-correction phrases

| Model | Course OK | Over-short (history) | Hist mean latency |
|-------|----------:|---------------------:|------------------:|
| Sotto base | 3/8 | 0/10 | 244 ms |
| **Sotto+ours** | **8/8** | **0/10** | 311 ms |
| LC-light (prior) | ~2/8 | 1/10 | ~166 ms |
| LC-smart (prior) | 6/8 | 5/10 | ~79 ms |

### Head-to-head (instance counts)

| | +ours better | base better | ties |
|--|-------------:|------------:|-----:|
| History | 2 | 4 | 4 |
| Course | 5 | 0 | 3 |

### Course details

**1.** `I wanna get the bag no not not not bag my phone`
- base ✗: I want to get the bag. Not not not bag my phone.
- +ours ✓: I want to get my phone.

**2.** `I wanna get my bag. No, no, not not bag, my phone.`
- base ✗: I want to get my bag. No, no, not a bag, my phone.
- +ours ✓: I want to get my phone.

**3.** `we should use Qwen wait no use Parakeet V3`
- base ✗: We should use Qwen. Wait, no, use Parakeet V3.
- +ours ✓: We should use Parakeet V3.

**4.** `ship version one point two point one no one point two point `
- base ✗: Ship version 1.2.1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0
- +ours ✓: Ship version 1.2.2.

**5.** `open settings uh no open transcription settings`
- base ✓: Open transcription settings.
- +ours ✓: Open transcription settings.

**6.** `put the keys at the top no no put them at the bottom collaps`
- base ✓: Put the keys at the bottom collapsed.
- +ours ✓: Put the keys at the bottom, collapsed.

**7.** `download the one point two billion parameter model no the th`
- base ✓: Download the 350 million parameter model.
- +ours ✓: Download the 350 million parameter model.

**8.** `Parquet V two no Parakeet V three for Europe`
- base ✗: Parquet V2 no Parakeet V3 for Europe.
- +ours ✗: Parakeet V3 for Europe.
