#!/usr/bin/env python3
"""Live try-out for the Sotto polish adapter — feel it before app integration.

Usage:
  python try_polish.py "grab oat milk no wait almond milk from the store"
  python try_polish.py            # interactive: type/paste lines, Enter to polish
  python try_polish.py --clipboard  # polish current macOS clipboard, copy result back
  python try_polish.py --base       # compare base vs +adapter side by side
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
MODEL = "juanquivilla/sotto-cleanup-lfm25-350m-mlx-5bit"
ADAPTER = ROOT / "adapters" / "sotto-lc-ft-clean"


def clean_out(s: str, raw: str) -> str:
    s = s.strip()
    for stop in ("### Input:", "### Output:", "\n###"):
        i = s.find(stop)
        if i != -1:
            s = s[:i].strip()
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="*")
    ap.add_argument("--adapter", type=Path, default=ADAPTER)
    ap.add_argument("--base", action="store_true", help="also show base output")
    ap.add_argument("--clipboard", action="store_true")
    args = ap.parse_args()

    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    sampler = make_sampler(temp=0.0)
    print(f"Loading {MODEL} + {args.adapter.name} ...", file=sys.stderr)
    model, tok = load(MODEL, adapter_path=str(args.adapter))
    base = load(MODEL) if args.base else None

    def run(m, t, raw):
        prompt = f"### Input:\n{raw.strip()}\n\n### Output:\n"
        mt = min(160, max(32, len(raw.split()) * 4))
        t0 = time.perf_counter()
        out = generate(m, t, prompt=prompt, max_tokens=mt, sampler=sampler, verbose=False)
        return clean_out(out if isinstance(out, str) else str(out), raw), time.perf_counter() - t0

    def show(raw):
        raw = raw.strip()
        if not raw:
            return
        if base:
            b, bt = run(base[0], base[1], raw)
            print(f"  base : {b}   ({bt*1000:.0f}ms)")
        o, ot = run(model, tok, raw)
        print(f"  ours : {o}   ({ot*1000:.0f}ms)")
        return o

    if args.clipboard:
        raw = subprocess.check_output(["pbpaste"], text=True)
        print(f"RAW: {raw}")
        o = show(raw)
        if o:
            subprocess.run(["pbcopy"], input=o, text=True)
            print("(copied polished text to clipboard)")
        return 0

    if args.text:
        raw = " ".join(args.text)
        print(f"RAW: {raw}")
        show(raw)
        return 0

    print("Interactive polish — type a line, Enter to polish, Ctrl-D to quit.\n",
          file=sys.stderr)
    for line in sys.stdin:
        show(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
