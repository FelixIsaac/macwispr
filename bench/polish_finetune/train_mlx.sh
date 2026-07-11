#!/usr/bin/env bash
# LoRA fine-tune LFM2.5 for dictation polish on Apple Silicon (mlx-lm).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/.venv-polish/bin/activate"

MODEL="${MODEL:-LiquidAI/LFM2.5-350M-MLX-4bit}"
DATA="${DATA:-$ROOT/polish_finetune/data}"
ADAPTER="${ADAPTER:-$ROOT/polish_finetune/adapters/lfm350-polish}"
ITERS="${ITERS:-400}"
BATCH="${BATCH:-2}"
LR="${LR:-1e-5}"
LAYERS="${LAYERS:-8}"
MAX_SEQ="${MAX_SEQ:-512}"

mkdir -p "$(dirname "$ADAPTER")"

if [[ ! -f "$DATA/train.jsonl" ]]; then
  echo "Building dataset..."
  python "$ROOT/polish_finetune/prepare_data.py" --out-dir "$DATA"
fi

echo "=== Train ==="
echo "model=$MODEL"
echo "data=$DATA"
echo "adapter=$ADAPTER"
echo "iters=$ITERS batch=$BATCH lr=$LR layers=$LAYERS max_seq=$MAX_SEQ"
echo

# Time the run
START=$(date +%s)

mlx_lm.lora \
  --model "$MODEL" \
  --train \
  --data "$DATA" \
  --fine-tune-type lora \
  --batch-size "$BATCH" \
  --iters "$ITERS" \
  --learning-rate "$LR" \
  --num-layers "$LAYERS" \
  --max-seq-length "$MAX_SEQ" \
  --mask-prompt \
  --adapter-path "$ADAPTER" \
  --save-every 100 \
  --steps-per-eval 50 \
  --steps-per-report 10 \
  --seed 42

END=$(date +%s)
echo "Wall time: $((END - START))s"
echo "Adapter written to $ADAPTER"
