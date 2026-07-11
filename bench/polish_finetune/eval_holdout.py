#!/usr/bin/env python3
"""Honest held-out eval: Sotto base vs Sotto+LoRA, graded by Grok-as-judge.

- Runs both models over data/holdout_eval.json (leak-checked, Grok-generated).
- Re-verifies zero leakage at runtime before scoring.
- Grades with the Grok CLI (batched, JSON schema):
    course:   honored self-correction? preserved meaning? over-short?
    light:    preserved meaning? not over-edited? over-short?
    preserve: left essentially unchanged?

Outputs a JSON + prints a summary table.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
GROK = "/Users/vas/.grok/bin/grok"

# Sotto native completion format (matches training).
def sotto_prompt(raw: str) -> str:
    return f"### Input:\n{raw.strip()}\n\n### Output:\n"


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def load_train_strings(train_dir: Path) -> set[str]:
    strings: set[str] = set()
    for name in ("train.jsonl", "valid.jsonl", "test.jsonl"):
        p = train_dir / name
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            text = json.loads(line)["text"]
            m = re.search(r"### Input:\n(.*?)\n\n### Output:\n(.*)", text, re.S)
            if m:
                strings.add(norm(m.group(1)))
                strings.add(norm(m.group(2)))
    return strings


def clean_out(s: str, raw: str) -> str:
    s = s.strip()
    # Stop at the next section marker if the model keeps going.
    for stop in ("### Input:", "### Output:", "\n###"):
        i = s.find(stop)
        if i != -1:
            s = s[:i].strip()
    # Take first line/paragraph if it rambles.
    if len(s.split()) > max(len(raw.split()) * 3, len(raw.split()) + 40):
        s = s.split("\n")[0].strip()
    return s


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "honored": {"type": "boolean"},
                    "preserved": {"type": "boolean"},
                    "over_short": {"type": "boolean"},
                    "over_edited": {"type": "boolean"},
                    "pass": {"type": "boolean"},
                    "note": {"type": "string"},
                },
                "required": ["id", "pass"],
            },
        }
    },
    "required": ["results"],
}


def judge(items: list[dict], model: str | None) -> dict[int, dict]:
    """items: {id, tag, raw, clean(ref), target, retract, out}. Returns id->verdict."""
    payload = [
        {k: it[k] for k in ("id", "tag", "raw", "reference", "retract", "target", "out")
         if k in it}
        for it in items
    ]
    prompt = f"""You are grading a voice-dictation cleanup model. For each item you
get the raw spoken text, a reference clean version, and the model OUTPUT. Judge
the OUTPUT (not the reference). Rules by tag:

- course: the speaker retracted `retract` and replaced it with `target`.
  honored = output keeps `target` and does NOT assert the retracted `retract`.
  preserved = same overall intent, nothing invented.
  over_short = dropped meaningful content.
  pass = honored AND preserved AND not over_short.

- light: fillers/stutters removed, meaning kept.
  preserved = all ideas kept, nothing invented. over_edited = meaning changed
  or content added/removed. over_short = truncated.
  pass = preserved AND not over_edited AND not over_short.

- preserve: the input was already clean.
  pass = output is essentially the same sentence (trivial punctuation/caps only),
  i.e. not over_edited.

Return JSON matching the schema, one result per id. Be strict but fair; minor
punctuation/casing differences are fine, and a number written as digits vs words
(7 vs seven, 9pm vs nine pm) counts as EQUIVALENT — never fail on that alone.

ITEMS:
{json.dumps(payload, ensure_ascii=False, indent=2)}"""
    cmd = [GROK, "-p", prompt, "--json-schema", json.dumps(JUDGE_SCHEMA),
           "--output-format", "json"]
    if model:
        cmd += ["-m", model]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        print(out.stderr, file=sys.stderr)
        raise SystemExit("grok judge failed")
    d = _extract(out.stdout)
    return {r["id"]: r for r in d["results"]}


def _extract(stdout: str) -> dict:
    cands = [stdout.strip()]
    for m in re.finditer(r"\{.*?\"results\".*\}", stdout, re.S):
        cands.append(m.group(0))
    try:
        wrap = json.loads(stdout.strip())
        for key in ("result", "text", "content", "response", "output"):
            v = wrap.get(key) if isinstance(wrap, dict) else None
            if isinstance(v, str):
                cands.append(v.strip())
    except Exception:
        pass
    for c in cands:
        try:
            d = json.loads(c)
            if isinstance(d, dict) and "results" in d:
                return d
        except Exception:
            continue
    raise SystemExit("Could not parse grok judge output:\n" + stdout[:2000])


def run_model(model_id: str, adapter: Path | None, evals: list[dict],
              max_tokens: int) -> list[dict]:
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    label = "base" if adapter is None else "+ours"
    print(f"\n#### {label}: {model_id}" + (f" + {adapter.name}" if adapter else ""),
          file=sys.stderr)
    if adapter is not None:
        model, tok = load(model_id, adapter_path=str(adapter))
    else:
        model, tok = load(model_id)
    sampler = make_sampler(temp=0.0)
    rows, lats = [], []
    for it in evals:
        prompt = sotto_prompt(it["raw"])
        mt = min(max_tokens, max(32, len(it["raw"].split()) * 4))
        t0 = time.perf_counter()
        out = generate(model, tok, prompt=prompt, max_tokens=mt, sampler=sampler,
                       verbose=False)
        dt = time.perf_counter() - t0
        lats.append(dt)
        text = clean_out(out if isinstance(out, str) else str(out), it["raw"])
        rows.append({**it, "out": text, "latency_s": round(dt, 3)})
    import mlx.core as mx
    del model, tok
    try:
        mx.metal.clear_cache()
    except Exception:
        pass
    return rows, sum(lats) / len(lats)


def score(judged: dict[int, dict], rows: list[dict]) -> dict:
    by_tag: dict[str, list[bool]] = {}
    for r in rows:
        v = judged.get(r["id"], {})
        by_tag.setdefault(r["tag"], []).append(bool(v.get("pass")))
    return {t: (sum(x), len(x)) for t, x in by_tag.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="juanquivilla/sotto-cleanup-lfm25-350m-mlx-5bit")
    ap.add_argument("--adapter", type=Path,
                    default=ROOT / "adapters" / "sotto-lc-ft-clean")
    ap.add_argument("--eval", type=Path, default=DATA / "holdout_eval_frozen.json")
    ap.add_argument("--train-dir", type=Path, default=DATA / "sotto_ft")
    ap.add_argument("--judge-model", default=None)
    ap.add_argument("--max-tokens", type=int, default=128)
    ap.add_argument("--out", type=Path,
                    default=ROOT.parent / "results" / "sotto_holdout_clean.json")
    args = ap.parse_args()

    evals = json.loads(args.eval.read_text())
    for i, it in enumerate(evals):
        it["id"] = i
        it["reference"] = it["clean"]

    # Runtime leak re-check — abort if any eval string is in training.
    train = load_train_strings(args.train_dir)
    leaked = [it["raw"] for it in evals
              if norm(it["raw"]) in train or norm(it["clean"]) in train]
    if leaked:
        print("ABORT — leakage detected in eval set:", file=sys.stderr)
        for l in leaked:
            print("  -", l, file=sys.stderr)
        return 1
    print(f"Leak-check OK: 0/{len(evals)} eval strings in training.", file=sys.stderr)

    base_rows, base_lat = run_model(args.model, None, evals, args.max_tokens)
    ours_rows, ours_lat = run_model(args.model, args.adapter, evals, args.max_tokens)

    print("\n[grok] judging base ...", file=sys.stderr)
    base_j = judge(base_rows, args.judge_model)
    print("[grok] judging +ours ...", file=sys.stderr)
    ours_j = judge(ours_rows, args.judge_model)

    base_score = score(base_j, base_rows)
    ours_score = score(ours_j, ours_rows)

    # Attach verdicts for the record.
    for r in base_rows:
        r["verdict"] = base_j.get(r["id"], {})
    for r in ours_rows:
        r["verdict"] = ours_j.get(r["id"], {})

    payload = {
        "eval_file": str(args.eval),
        "n": len(evals),
        "leak_free": True,
        "base": {"model": args.model, "latency_mean_s": round(base_lat, 3),
                 "score": base_score, "rows": base_rows},
        "ours": {"model": args.model, "adapter": args.adapter.name,
                 "latency_mean_s": round(ours_lat, 3),
                 "score": ours_score, "rows": ours_rows},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    def fmt(s):
        return "  ".join(f"{t} {a}/{b}" for t, (a, b) in sorted(s.items()))

    print("\n=== HELD-OUT (leak-free) RESULTS ===")
    print(f"{'model':12} {'course':>10} {'light':>10} {'preserve':>10} {'lat':>8}")
    def row(name, sc, lat):
        c = sc.get("course", (0, 0)); l = sc.get("light", (0, 0)); p = sc.get("preserve", (0, 0))
        print(f"{name:12} {c[0]:>4}/{c[1]:<5} {l[0]:>4}/{l[1]:<5} "
              f"{p[0]:>4}/{p[1]:<5} {lat*1000:>5.0f}ms")
    row("Sotto base", base_score, base_lat)
    row("Sotto+ours", ours_score, ours_lat)
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
