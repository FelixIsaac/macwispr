#!/usr/bin/env python3
"""Generate a LEAK-FREE held-out eval set for the Sotto polish LoRA.

Uses the Grok CLI (`grok -p` with a JSON schema) as the data generator so the
eval phrases are on *different* topics than the training set. Then runs a hard
leak-check against train/valid and drops anything that overlaps.

Output: bench/polish_finetune/data/holdout_eval.json
  [ {raw, clean, tag, retract?, target?}, ... ]

tags: course | light | preserve
  - course: self-correction ("no, not X, Y") -> clean must honor Y, drop X
  - light:  fillers/stutters/false starts     -> clean keeps meaning, tidier
  - preserve: already clean                    -> clean == raw (anti over-edit)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
GROK = "/Users/vas/.grok/bin/grok"

# Topics the TRAINING set already uses — Grok must avoid these so we test
# generalization, not memorization.
BANNED_TOPICS = [
    "bag / phone", "Qwen", "Parakeet", "MacWispr", "telemetry", "hotkey",
    "Option Space", "1.2B / 350M / 0.6B / 1.7B model sizes", "Slack vs email",
    "Tuesday/Wednesday meeting", "milk / eggs", "Kafka / RabbitMQ",
    "staging / production", "GitLab / GitHub", "listening banner", "menu bar",
    "version 1.2.1 / 1.2.2", "WER", "PostHog", "RAM gigabytes",
]

SCHEMA = {
    "type": "object",
    "properties": {
        "course": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw": {"type": "string"},
                    "clean": {"type": "string"},
                    "retract": {"type": "string"},
                    "target": {"type": "string"},
                },
                "required": ["raw", "clean", "retract", "target"],
            },
        },
        "light": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw": {"type": "string"},
                    "clean": {"type": "string"},
                },
                "required": ["raw", "clean"],
            },
        },
        "preserve": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["course", "light", "preserve"],
}


def build_prompt(n_course: int, n_light: int, n_preserve: int) -> str:
    banned = "\n".join(f"  - {t}" for t in BANNED_TOPICS)
    return f"""You are generating a HELD-OUT evaluation set for a voice-dictation
cleanup model. These phrases must test whether the model GENERALIZES, so they
must be on FRESH topics that do NOT reuse any of these already-used themes:
{banned}

Invent everyday, work, cooking, travel, coding, and errand topics of your own
that are NOT in that list.

Produce THREE groups:

1. course ({n_course} items): a spoken utterance with a self-correction where the
   speaker retracts something and replaces it. Pattern like
   "book the 7pm flight no wait the 9pm one" -> "Book the 9pm flight."
   - raw: messy spoken text WITH the retraction
   - clean: the correctly written sentence that HONORS the correction (drops the
     retracted item, keeps the replacement)
   - retract: the thing that was retracted (e.g. "7pm flight")
   - target: the final intended thing (e.g. "9pm flight")
   Vary the retraction cue: "no", "no wait", "not X, Y", "scratch that", "I mean".

2. light ({n_light} items): spoken text with fillers/stutters/false starts but NO
   meaning change. clean = same meaning, tidy grammar/caps/punctuation, keep all
   ideas, do not summarize.

3. preserve ({n_preserve} items): already-clean written sentences that should be
   returned essentially unchanged (test for over-editing). Just strings.

Keep sentences realistic and 6-20 words. Output ONLY JSON matching the schema."""


def grok_generate(n_course: int, n_light: int, n_preserve: int, model: str | None) -> dict:
    cmd = [GROK, "-p", build_prompt(n_course, n_light, n_preserve),
           "--json-schema", json.dumps(SCHEMA), "--output-format", "json"]
    if model:
        cmd += ["-m", model]
    print(f"[grok] generating {n_course} course / {n_light} light / {n_preserve} preserve ...",
          file=sys.stderr)
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        print(out.stderr, file=sys.stderr)
        raise SystemExit(f"grok failed (exit {out.returncode})")
    return extract_json(out.stdout)


def extract_json(stdout: str) -> dict:
    """grok --output-format json wraps the turn; the model payload is JSON text.
    Be liberal: find the payload object with course/light/preserve keys."""
    # Try: whole stdout is the wrapper json with a result/text field.
    candidates: list[str] = []
    stripped = stdout.strip()
    candidates.append(stripped)
    # Pull any {...} blocks that mention our keys.
    for m in re.finditer(r"\{.*?\"course\".*?\"preserve\".*?\}", stdout, re.S):
        candidates.append(m.group(0))
    # Also try to parse wrapper then dig for a string field containing our JSON.
    try:
        wrap = json.loads(stripped)
        for key in ("result", "text", "content", "response", "output"):
            v = wrap.get(key) if isinstance(wrap, dict) else None
            if isinstance(v, str):
                candidates.append(v.strip())
    except Exception:
        pass
    for c in candidates:
        try:
            d = json.loads(c)
            if isinstance(d, dict) and {"course", "light", "preserve"} <= set(d):
                return d
        except Exception:
            continue
    # Last resort: greedy outermost object
    m = re.search(r"\{.*\}", stdout, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            if {"course", "light", "preserve"} <= set(d):
                return d
        except Exception:
            pass
    raise SystemExit("Could not parse JSON from grok output:\n" + stdout[:2000])


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def load_train_strings(data_dir: Path) -> set[str]:
    """All raw+clean strings currently in the sotto_ft splits (train+valid+test)."""
    strings: set[str] = set()
    for name in ("train.jsonl", "valid.jsonl", "test.jsonl"):
        p = data_dir / name
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            text = json.loads(line)["text"]
            # format: ### Input:\n{raw}\n\n### Output:\n{clean}
            m = re.search(r"### Input:\n(.*?)\n\n### Output:\n(.*)", text, re.S)
            if m:
                strings.add(norm(m.group(1)))
                strings.add(norm(m.group(2)))
    return strings


def leak_check(items: list[dict], train: set[str]) -> tuple[list[dict], list[dict]]:
    kept, dropped = [], []
    for it in items:
        raw_n, clean_n = norm(it["raw"]), norm(it["clean"])
        if raw_n in train or clean_n in train:
            dropped.append(it)
        else:
            kept.append(it)
    return kept, dropped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--course", type=int, default=16)
    ap.add_argument("--light", type=int, default=12)
    ap.add_argument("--preserve", type=int, default=8)
    ap.add_argument("--model", default=None, help="grok model id (default: grok CLI default)")
    ap.add_argument("--train-dir", type=Path, default=DATA / "sotto_ft")
    ap.add_argument("--out", type=Path, default=DATA / "holdout_eval.json")
    args = ap.parse_args()

    gen = grok_generate(args.course, args.light, args.preserve, args.model)

    items: list[dict] = []
    for c in gen.get("course", []):
        items.append({"tag": "course", "raw": c["raw"], "clean": c["clean"],
                      "retract": c.get("retract", ""), "target": c.get("target", "")})
    for l in gen.get("light", []):
        items.append({"tag": "light", "raw": l["raw"], "clean": l["clean"]})
    for p in gen.get("preserve", []):
        items.append({"tag": "preserve", "raw": p, "clean": p})

    # Dedup within the eval set by normalized raw.
    seen, deduped = set(), []
    for it in items:
        k = norm(it["raw"])
        if k in seen:
            continue
        seen.add(k)
        deduped.append(it)

    train = load_train_strings(args.train_dir)
    kept, dropped = leak_check(deduped, train)

    by_tag: dict[str, int] = {}
    for it in kept:
        by_tag[it["tag"]] = by_tag.get(it["tag"], 0) + 1

    args.out.write_text(json.dumps(kept, indent=2, ensure_ascii=False))
    print(f"\nGenerated: {len(deduped)}  Kept (leak-free): {len(kept)}  "
          f"Dropped (leak): {len(dropped)}")
    print("By tag:", by_tag)
    if dropped:
        print("\nLEAKED (excluded):")
        for d in dropped:
            print("  -", d["raw"][:70])
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
