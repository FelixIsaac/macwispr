#!/usr/bin/env python3
"""Side-by-side eval: base vs LoRA adapter on history samples."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

SYSTEM = (
    "Clean this voice dictation for typing into an app. "
    "Keep every idea the speaker said; do not summarize. "
    "Remove stutters, repeated words, and fillers. "
    "Fix light grammar, punctuation, and capitalization. "
    "Output only the cleaned text."
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="LiquidAI/LFM2.5-350M-MLX-4bit")
    ap.add_argument(
        "--adapter",
        type=Path,
        default=Path(__file__).parent / "adapters" / "lfm350-polish",
    )
    ap.add_argument(
        "--samples",
        type=Path,
        default=Path(__file__).parent.parent / "data" / "polish_history_sample.json",
    )
    ap.add_argument("--max-samples", type=int, default=6)
    args = ap.parse_args()

    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    samples = json.loads(args.samples.read_text())[: args.max_samples]
    sampler = make_sampler(temp=0.1)

    print(f"Loading base {args.model} ...")
    model, tokenizer = load(args.model)
    if args.adapter.exists():
        print(f"Loading adapter {args.adapter} ...")
        model, tokenizer = load(args.model, adapter_path=str(args.adapter))
    else:
        print("WARNING: adapter path missing; evaluating base only")

    for i, s in enumerate(samples, 1):
        raw = s["text"].strip()
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": raw},
        ]
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        t0 = time.perf_counter()
        out = generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=min(256, max(48, len(raw.split()) * 4)),
            sampler=sampler,
            verbose=False,
        )
        dt = time.perf_counter() - t0
        print(f"\n── [{i}] {dt:.3f}s ──")
        print(f"RAW: {raw}")
        print(f"OUT: {out if isinstance(out, str) else str(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
