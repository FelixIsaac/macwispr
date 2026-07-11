#!/usr/bin/env python3
"""Polish-model bench v2: prompt A/B, memory RSS, latency overhead.

Compares cleanup quality + resource cost for LFM2.5 / Qwen3 small MLX models.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import resource
import subprocess
import sys
import time
from pathlib import Path

# Strict cleanup — less rewrite, no summary, no meta
PROMPT_STRICT = """You edit raw voice-dictation transcripts.
Rules:
1. Output ONLY the cleaned transcript — no labels, no quotes, no commentary.
2. Keep every idea the speaker said. Do NOT summarize or shorten.
3. Remove stutters and exact word repeats (e.g. "that that that" → "that", "as a as a" → "as a").
4. Fix grammar, punctuation, and capitalization lightly.
5. Do not invent names, numbers, or facts that were not spoken.
6. Do not answer questions in the transcript — only clean the text."""

# Slightly more Flow-like polish, still no summarization
PROMPT_FLOW = """Clean this voice dictation for typing into an app.
Speak-to-text often has false starts, fillers, and missing punctuation.
Return a natural written version of what they meant to say.
Keep the full meaning and roughly the same length — do not summarize.
Output only the cleaned text, nothing else."""

PROMPTS = {
    "strict": PROMPT_STRICT,
    "flow": PROMPT_FLOW,
}


def rss_mb() -> float:
    """Current process RSS in MiB (macOS: ru_maxrss is bytes)."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # On Linux ru_maxrss is KB; on macOS it's bytes.
    val = float(usage.ru_maxrss)
    if sys.platform == "darwin":
        return val / (1024 * 1024)
    return val / 1024


def current_rss_mb() -> float:
    """Live RSS via ps (maxrss is high-water, not live)."""
    try:
        out = subprocess.check_output(
            ["ps", "-o", "rss=", "-p", str(os.getpid())], text=True
        ).strip()
        # ps rss is in KB on macOS
        return float(out) / 1024
    except Exception:
        return rss_mb()


def sanitize(output: str, original: str) -> str:
    s = output.strip()
    # Drop thinking blocks if present (Qwen3)
    s = re.sub(r"<think>[\s\S]*?</think>", "", s, flags=re.I).strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        if len(s) > 1:
            s = s[1:-1].strip()
    for prefix in (
        "Corrected:",
        "Transcript:",
        "Output:",
        "Cleaned:",
        "Here is the corrected text:",
        "Here's the cleaned transcript:",
        "Here is the cleaned transcript:",
    ):
        if s.lower().startswith(prefix.lower()):
            s = s[len(prefix) :].strip()
    # Hallucination length guard
    if len(s) > max(len(original) * 3, len(original) + 80):
        return original
    # Collapse if model summarized to tiny fragment of long input
    if len(original.split()) >= 25 and len(s.split()) < max(5, len(original.split()) // 4):
        # keep short output but flag later via metrics
        pass
    return s


def build_prompt(tokenizer, system: str, user_text: str) -> str:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text},
    ]
    if hasattr(tokenizer, "apply_chat_template"):
        kwargs = dict(tokenize=False, add_generation_prompt=True)
        # Qwen3 thinking off when supported
        try:
            return tokenizer.apply_chat_template(
                messages, enable_thinking=False, **kwargs
            )
        except TypeError:
            try:
                return tokenizer.apply_chat_template(messages, **kwargs)
            except Exception:
                pass
    return f"{system}\n\nTranscript:\n{user_text}\n\nCleaned:"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--samples",
        type=Path,
        default=Path(__file__).parent / "data" / "polish_history_sample.json",
    )
    ap.add_argument(
        "--models",
        nargs="+",
        default=[
            "LiquidAI/LFM2.5-230M-MLX-4bit",
            "LiquidAI/LFM2.5-350M-MLX-4bit",
            "mlx-community/Qwen3-0.6B-4bit",
            "mlx-community/Qwen3.5-0.8B-4bit",
        ],
    )
    ap.add_argument("--prompts", nargs="+", default=["strict", "flow"])
    ap.add_argument("--max-samples", type=int, default=None)
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--temp", type=float, default=0.1)
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent / "results" / "polish_prompt_mem_v2.json",
    )
    args = ap.parse_args()

    samples = json.loads(args.samples.read_text())
    if args.max_samples:
        samples = samples[: args.max_samples]

    chip = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
    mem_sys = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True)) / 1e9

    print("=== Polish bench v2 (prompt + memory) ===")
    print(f"Machine: {chip} · {mem_sys:.0f} GB")
    print(f"Samples: {len(samples)}  Prompts: {args.prompts}")
    print()

    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    sampler = make_sampler(temp=args.temp)
    all_runs = []

    for model_id in args.models:
        print(f"\n######## {model_id} ########")
        rss_before = current_rss_mb()
        t0 = time.perf_counter()
        try:
            model, tokenizer = load(model_id)
        except Exception as e:
            print(f"LOAD FAILED: {e}")
            all_runs.append({"model": model_id, "error": str(e)})
            continue
        load_s = time.perf_counter() - t0
        rss_after_load = current_rss_mb()
        peak_after_load = rss_mb()
        mem_delta = rss_after_load - rss_before

        print(
            f"Load {load_s:.2f}s | RSS before {rss_before:.0f} MiB → after {rss_after_load:.0f} MiB "
            f"(Δ {mem_delta:.0f} MiB) | maxrss {peak_after_load:.0f} MiB"
        )

        # Warmup once per model
        warm_prompt = build_prompt(tokenizer, PROMPT_STRICT, "Hello this is a short test.")
        tw = time.perf_counter()
        _ = generate(model, tokenizer, prompt=warm_prompt, max_tokens=32, sampler=sampler, verbose=False)
        warm_s = time.perf_counter() - tw
        rss_after_warm = current_rss_mb()
        print(f"Warmup {warm_s:.2f}s | RSS {rss_after_warm:.0f} MiB")

        for pname in args.prompts:
            system = PROMPTS[pname]
            latencies = []
            rows = []
            over_short = 0
            changed = 0

            for i, sample in enumerate(samples, 1):
                raw = sample["text"].strip()
                wc = sample.get("wordCount") or len(raw.split())
                max_tok = min(args.max_tokens, max(48, wc * 4))
                prompt = build_prompt(tokenizer, system, raw)

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
                text = sanitize(out if isinstance(out, str) else str(out), raw)
                if text.strip() != raw.strip():
                    changed += 1
                if len(raw.split()) >= 25 and len(text.split()) < max(5, len(raw.split()) // 4):
                    over_short += 1

                rows.append(
                    {
                        "index": i,
                        "word_count": wc,
                        "latency_s": round(dt, 3),
                        "raw": raw,
                        "cleaned": text,
                        "out_words": len(text.split()),
                        "over_short": len(raw.split()) >= 25
                        and len(text.split()) < max(5, len(raw.split()) // 4),
                    }
                )
                flag = " ⚠SHORT" if rows[-1]["over_short"] else ""
                print(f"  [{pname}][{i}/{len(samples)}] {dt:.3f}s{flag}")
                print(f"    RAW: {raw[:100]}{'…' if len(raw)>100 else ''}")
                print(f"    OUT: {text[:100]}{'…' if len(text)>100 else ''}")

            rss_end = current_rss_mb()
            mean_l = sum(latencies) / len(latencies)
            p50 = sorted(latencies)[len(latencies) // 2]
            run = {
                "model": model_id,
                "prompt": pname,
                "load_s": round(load_s, 3),
                "warmup_s": round(warm_s, 3),
                "rss_before_mib": round(rss_before, 1),
                "rss_after_load_mib": round(rss_after_load, 1),
                "rss_after_warmup_mib": round(rss_after_warm, 1),
                "rss_end_mib": round(rss_end, 1),
                "rss_delta_load_mib": round(mem_delta, 1),
                "maxrss_mib": round(rss_mb(), 1),
                "latency_mean_s": round(mean_l, 3),
                "latency_p50_s": round(p50, 3),
                "latency_min_s": round(min(latencies), 3),
                "latency_max_s": round(max(latencies), 3),
                "changed": changed,
                "over_short": over_short,
                "n": len(samples),
                "results": rows,
            }
            all_runs.append(run)
            print(
                f"  → {pname}: mean {mean_l:.3f}s p50 {p50:.3f}s  "
                f"changed {changed}/{len(samples)}  over-short {over_short}  "
                f"RSS end {rss_end:.0f} MiB"
            )

        # Free model between runs (best-effort)
        del model, tokenizer
        try:
            import mlx.core as mx

            mx.metal.clear_cache()
        except Exception:
            pass

    payload = {
        "machine": {"chip": chip, "ram_gb": round(mem_sys, 1), "platform": platform.platform()},
        "runs": all_runs,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))
    print(f"\nWrote {args.out}")

    # Compact table
    print("\n=== SUMMARY ===")
    print(
        f"{'model':40} {'prompt':7} {'load':>6} {'mean':>7} {'p50':>7} "
        f"{'ΔRSS':>7} {'short':>5} {'chg':>5}"
    )
    for r in all_runs:
        if "error" in r:
            print(f"{r['model'][:40]:40} ERROR {r['error'][:40]}")
            continue
        mid = r["model"].split("/")[-1][:40]
        print(
            f"{mid:40} {r['prompt']:7} {r['load_s']:5.1f}s {r['latency_mean_s']:6.3f}s "
            f"{r['latency_p50_s']:6.3f}s {r['rss_delta_load_mib']:6.0f}M "
            f"{r['over_short']:5} {r['changed']:3}/{r['n']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
