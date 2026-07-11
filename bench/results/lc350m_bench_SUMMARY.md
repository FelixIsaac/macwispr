# LC-350M benchmark (M5 · history + course-correction)

Compared **base LFM2.5-350M** vs fused **LC-350M-light** vs **LC-350M-smart** on:

- 10 real MacWispr history clips  
- 8 course-correction phrases (bag→phone style)

## Latency

| Model | Load | History mean | Course mean |
|-------|-----:|-------------:|------------:|
| Base LFM2.5-350M | 0.6s | **66 ms** | 34 ms |
| **LC-350M-light** | 0.2s | **166 ms** | 46 ms |
| **LC-350M-smart** | 0.2s | **79 ms** | **40 ms** |

All fine-tunes stay **sub-200 ms** cleanup on M5.

## Quality

| Model | History over-short (bad drop) | Course-correction hits |
|-------|------------------------------:|-----------------------:|
| Base | **8/10** (often collapses / garbage) | **1/8** |
| **LC-350M-light** | **1/10** (best keep-all) | 4/8 (weak on repairs) |
| **LC-350M-smart** | 5/10 (still over-trims long rants) | **6/8** (bag→phone works) |

### Course-correction examples (smart)

| Raw | LC-350M-smart |
|-----|----------------|
| I wanna get the bag no not not not bag my phone | I want to get the phone. |
| we should use Qwen wait no use Parakeet V3 | We should use Parakeet V3. |
| put the keys at the top no no put them at the bottom collapsed | put the keys at the bottom collapsed |

### Takeaway

- **Light** = safer for long dictations (keeps content).  
- **Smart** = better at self-repairs; still needs more data so it doesn’t over-summarize long product rants.  
- **Base** = not usable as a polish model for this task.

Raw JSON: `lc350m_bench.json`
