#!/usr/bin/env python3
"""Benchmark on-device polish models on real MacWispr history transcripts.

Measures latency (load + per-sample + total) and prints before/after text.
Default model: mlx-community/gemma-3-270m-it-4bit (Gemma 3 270M instruct, 4-bit).
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

PROMPT = """You are a careful editor for voice dictation transcripts.
Fix grammar, punctuation, capitalization, and sentence structure.
Remove stutters and repeated words (e.g. "that that that" → "that").
Keep the original meaning and wording as close as possible.
Do not add explanations, quotes, or commentary.
Output only the corrected transcript."""


def rule_based_postprocess(text: str, remove_fillers: bool = True) -> str:
    """Mirror MacWispr AppState.postProcess (fillers + first-letter cap)."""
    result = text.strip()
    if remove_fillers:
        fillers = [
            "uh", "um", "like", "you know", "I mean", "so", "actually", "basically", "right",
        ]
        for filler in fillers:
            result = re.sub(rf"\b{re.escape(filler)}\b[,]?\s*", "", result, flags=re.I)
        while "  " in result:
            result = result.replace("  ", " ")
    if result:
        result = result[0].upper() + result[1:]
    return result.strip()


def sanitize(output: str, original: str) -> str:
    s = output.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        if len(s) > 1:
            s = s[1:-1].strip()
    for prefix in (
        "Corrected:",
        "Transcript:",
        "Output:",
        "Here is the corrected text:",
        "Here's the corrected transcript:",
    ):
        if s.lower().startswith(prefix.lower()):
            s = s[len(prefix) :].strip()
    if len(s) > max(len(original) * 3, len(original) + 80):
        return original
    return s


def machine_info() -> dict:
    mem = None
    try:
        raw = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
        mem = round(int(raw) / (1024**3), 1)
    except Exception:
        pass
    chip = None
    try:
        chip = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
    except Exception:
        pass
    return {
        "chip": chip or platform.processor() or "unknown",
        "ram_gb": mem,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
    }


def load_samples(path: Path, max_samples: int | None) -> list[dict]:
    data = json.loads(path.read_text())
    if max_samples is not None:
        data = data[:max_samples]
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--samples",
        type=Path,
        default=Path(__file__).parent / "data" / "polish_history_sample.json",
    )
    ap.add_argument(
        "--model",
        default="mlx-community/gemma-3-270m-it-4bit",
        help="HF mlx-community model id",
    )
    ap.add_argument("--max-samples", type=int, default=None)
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--temp", type=float, default=0.2)
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent / "results" / "polish_gemma270m.json",
    )
    args = ap.parse_args()

    samples = load_samples(args.samples, args.max_samples)
    if not samples:
        print("No samples", file=sys.stderr)
        return 1

    info = machine_info()
    print("=== MacWispr polish benchmark ===")
    print(f"Machine: {info['chip']} · {info['ram_gb']} GB RAM")
    print(f"Model:   {args.model}")
    print(f"Samples: {len(samples)} (from {args.samples})")
    print()

    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    t0 = time.perf_counter()
    model, tokenizer = load(args.model)
    load_s = time.perf_counter() - t0
    print(f"Load time: {load_s:.2f}s")
    print()

    sampler = make_sampler(temp=args.temp)
    results = []
    latencies = []

    # Warmup (first token / Metal compile)
    warm = "Hello world this is a short test of dictation cleanup."
    warm_msgs = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": warm},
    ]
    if hasattr(tokenizer, "apply_chat_template"):
        warm_prompt = tokenizer.apply_chat_template(
            warm_msgs, tokenize=False, add_generation_prompt=True
        )
    else:
        warm_prompt = f"{PROMPT}\n\n{warm}"
    t_w = time.perf_counter()
    _ = generate(
        model,
        tokenizer,
        prompt=warm_prompt,
        max_tokens=64,
        sampler=sampler,
        verbose=False,
    )
    warm_s = time.perf_counter() - t_w
    print(f"Warmup:   {warm_s:.2f}s")
    print()

    for i, sample in enumerate(samples, 1):
        raw = sample["text"].strip()
        rule = rule_based_postprocess(raw)
        wc = sample.get("wordCount") or len(raw.split())
        max_tok = min(args.max_tokens, max(32, wc * 3))

        messages = [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": raw},
        ]
        if hasattr(tokenizer, "apply_chat_template"):
            prompt = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        else:
            prompt = f"{PROMPT}\n\nTranscript:\n{raw}\n\nCorrected:"

        t1 = time.perf_counter()
        out = generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=max_tok,
            sampler=sampler,
            verbose=False,
        )
        dt = time.perf_counter() - t1
        latencies.append(dt)
        cleaned = sanitize(out if isinstance(out, str) else str(out), raw)

        row = {
            "index": i,
            "word_count": wc,
            "latency_s": round(dt, 3),
            "raw": raw,
            "rule_based": rule,
            "gemma_270m": cleaned,
            "changed_vs_raw": cleaned.strip() != raw.strip(),
            "changed_vs_rule": cleaned.strip() != rule.strip(),
        }
        results.append(row)

        print(f"── [{i}/{len(samples)}] {wc} words · {dt:.3f}s ──")
        print(f"RAW:   {raw}")
        print(f"RULE:  {rule}")
        print(f"GEMMA: {cleaned}")
        print()

    if latencies:
        avg = sum(latencies) / len(latencies)
        p50 = sorted(latencies)[len(latencies) // 2]
        mx = max(latencies)
        mn = min(latencies)
        print("=== Latency summary (post-warmup, generate only) ===")
        print(f"  n={len(latencies)}  mean={avg:.3f}s  p50={p50:.3f}s  min={mn:.3f}s  max={mx:.3f}s")
        print(f"  load={load_s:.2f}s  warmup={warm_s:.2f}s")
        print(f"  changed_vs_raw={sum(1 for r in results if r['changed_vs_raw'])}/{len(results)}")

    payload = {
        "machine": info,
        "model": args.model,
        "prompt": PROMPT,
        "load_s": round(load_s, 3),
        "warmup_s": round(warm_s, 3),
        "latency_mean_s": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "latency_p50_s": round(sorted(latencies)[len(latencies) // 2], 3) if latencies else None,
        "latency_min_s": round(min(latencies), 3) if latencies else None,
        "latency_max_s": round(max(latencies), 3) if latencies else None,
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
