#!/usr/bin/env python3
"""Batched Grok generator for dictation-cleanup pairs (train pool OR eval).

Design goals learned from the leak fiasco + the held-out failure modes:
  - Diversity: rotate fresh domains + retraction cues across batches.
  - Context preservation: long course utterances whose target KEEPS all the
    non-retracted clauses (attacks the "dropped a clause" over-short failure).
  - Stacked corrections: ~20% of course items retract twice.
  - Digits policy: numbers rendered as digits in every clean target.
  - QC: optional Grok pass that drops pairs where the target doesn't honor the
    correction, over-shortens, or invents content.
  - Leak-safe: dedup within pool and against an --avoid set (normalized).

Output: JSONL of {tag, raw, clean, retract?, target?}.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
GROK = "/Users/vas/.grok/bin/grok"

BANNED_TOPICS = [
    "bag / phone", "Qwen", "Parakeet", "MacWispr", "telemetry", "hotkey",
    "Option Space", "model sizes like 1.2B/350M/0.6B/1.7B", "Slack vs email",
    "listening banner", "menu bar", "WER", "PostHog",
]

DOMAINS = [
    "cooking & recipes", "home repair & DIY", "gardening & plants",
    "travel & flights", "restaurant & reservations", "groceries & errands",
    "software & coding", "car maintenance", "personal finance & bills",
    "fitness & sports", "medical & pharmacy", "school & kids",
    "moving & logistics", "photography & video", "music & instruments",
    "pets & vet", "weddings & events", "real estate & rentals",
    "office & meetings", "shopping & returns", "camping & outdoors",
    "email & scheduling", "cleaning & chores", "hobbies & crafts",
]

CUES = [
    'plain "no" (… no …)', '"no wait"', '"not X, Y"', '"scratch that"',
    '"I mean"', '"actually"', '"hold on"', '"make that"', '"or rather"',
    '"sorry, Y" self-fix',
]

COURSE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "raw": {"type": "string"}, "clean": {"type": "string"},
            "retract": {"type": "string"}, "target": {"type": "string"},
        },
        "required": ["raw", "clean", "retract", "target"]}}},
    "required": ["items"],
}
LIGHT_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"raw": {"type": "string"}, "clean": {"type": "string"}},
        "required": ["raw", "clean"]}}},
    "required": ["items"],
}
PRESERVE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "string"}}},
    "required": ["items"],
}

DIGITS_RULE = ("Render all numbers as DIGITS in every clean target "
               "(seven -> 7, three seventy-five -> 375, nine pm -> 9pm, "
               "two-day -> 2-day). Keep the digit form consistent.")


def course_prompt(k: int, domains: list[str], cues: list[str], stacked: int) -> str:
    return f"""Generate {k} voice-dictation SELF-CORRECTION examples for a cleanup
model's TRAINING data. Draw ONLY from these domains: {', '.join(domains)}.
Do NOT use any of these already-used themes: {', '.join(BANNED_TOPICS)}.

Each item: the speaker starts saying something, RETRACTS part of it, and
replaces it. Emphasize these retraction cues across the batch: {', '.join(cues)}.

CRITICAL rules:
- raw = messy spoken text WITH the retraction, 10-22 words, realistic.
- clean = the correctly written sentence that HONORS the correction: drop the
  retracted thing, keep the replacement, and KEEP EVERY OTHER CLAUSE of the
  sentence (do NOT shorten to just the corrected fragment). E.g.
  "take the coastal highway to the cabin not the coastal, the inland route"
  -> "Take the inland route to the cabin." (keeps "to the cabin").
- {stacked} of the {k} items must contain TWO corrections in one utterance.
- retract = the retracted thing; target = the final intended thing.
- {DIGITS_RULE}
Output ONLY JSON matching the schema."""


def light_prompt(k: int, domains: list[str]) -> str:
    return f"""Generate {k} voice-dictation cleanup examples (fillers/stutters/
false starts, NO meaning change) for TRAINING data. Domains: {', '.join(domains)}.
Avoid these themes: {', '.join(BANNED_TOPICS)}.
- raw = spoken text with um/uh/like/you know/repeats/false starts, 8-20 words.
- clean = same meaning, tidy grammar/caps/punctuation, keep ALL ideas, do NOT
  summarize or drop content. {DIGITS_RULE}
Output ONLY JSON matching the schema."""


def preserve_prompt(k: int, domains: list[str]) -> str:
    return f"""Generate {k} already-clean written sentences (6-18 words) for
TRAINING data — these test that the model does NOT over-edit. Domains:
{', '.join(domains)}. Avoid themes: {', '.join(BANNED_TOPICS)}.
{DIGITS_RULE} Output ONLY JSON: a list of strings under "items"."""


def grok(prompt: str, schema: dict, model: str | None, timeout: int = 300) -> dict:
    cmd = [GROK, "-p", prompt, "--json-schema", json.dumps(schema),
           "--output-format", "json"]
    if model:
        cmd += ["-m", model]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        print(out.stderr[:500], file=sys.stderr)
        return {"items": []}
    return extract(out.stdout, "items")


def extract(stdout: str, key: str) -> dict:
    cands = [stdout.strip()]
    for m in re.finditer(r"\{[^{}]*\"" + key + r"\"[\s\S]*?\}\s*$", stdout, re.M):
        cands.append(m.group(0))
    try:
        wrap = json.loads(stdout.strip())
        for k in ("result", "text", "content", "response", "output"):
            v = wrap.get(k) if isinstance(wrap, dict) else None
            if isinstance(v, str):
                cands.append(v.strip())
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", stdout)
    if m:
        cands.append(m.group(0))
    for c in cands:
        try:
            d = json.loads(c)
            if isinstance(d, dict) and key in d:
                return d
        except Exception:
            continue
    return {key: []}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


QC_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "ok": {"type": "boolean"}},
        "required": ["id", "ok"]}}},
    "required": ["results"],
}


def qc_course(items: list[dict], model: str | None) -> list[dict]:
    """Drop course pairs where the target doesn't honor the correction / is bad."""
    kept: list[dict] = []
    for i in range(0, len(items), 30):
        chunk = items[i:i + 30]
        payload = [{"id": j, "raw": it["raw"], "clean": it["clean"],
                    "retract": it["retract"], "target": it["target"]}
                   for j, it in enumerate(chunk)]
        prompt = f"""QC these self-correction training pairs. For each, ok=true ONLY if
the clean target: (1) contains the `target`, (2) does NOT assert the retracted
`retract`, (3) keeps the other clauses (not over-shortened), (4) invents nothing,
(5) numbers are digits. Else ok=false. Return JSON.\n{json.dumps(payload, ensure_ascii=False)}"""
        d = grok(prompt, QC_SCHEMA, model)
        verd = {r["id"]: r.get("ok", False) for r in d.get("results", [])}
        for j, it in enumerate(chunk):
            if verd.get(j, False):
                kept.append(it)
    return kept


def gen_bucket(tag: str, n: int, batch: int, model: str, rng: random.Random,
               avoid: set[str], pool_keys: set[str]) -> list[dict]:
    got: list[dict] = []
    attempts = 0
    while len(got) < n and attempts < n // batch + 8:
        attempts += 1
        doms = rng.sample(DOMAINS, k=min(4, len(DOMAINS)))
        if tag == "course":
            cues = rng.sample(CUES, k=4)
            stacked = max(1, batch // 5)
            d = grok(course_prompt(batch, doms, cues, stacked), COURSE_SCHEMA, model)
            raws = [{"tag": "course", "raw": x["raw"], "clean": x["clean"],
                     "retract": x.get("retract", ""), "target": x.get("target", "")}
                    for x in d.get("items", []) if x.get("raw") and x.get("clean")]
        elif tag == "light":
            d = grok(light_prompt(batch, doms), LIGHT_SCHEMA, model)
            raws = [{"tag": "light", "raw": x["raw"], "clean": x["clean"]}
                    for x in d.get("items", []) if x.get("raw") and x.get("clean")]
        else:
            d = grok(preserve_prompt(batch, doms), PRESERVE_SCHEMA, model)
            raws = [{"tag": "preserve", "raw": s, "clean": s}
                    for s in d.get("items", []) if isinstance(s, str) and s.strip()]
        added = 0
        for it in raws:
            k = norm(it["raw"])
            if not k or k in avoid or k in pool_keys or norm(it["clean"]) in avoid:
                continue
            pool_keys.add(k)
            got.append(it)
            added += 1
        print(f"  [{tag}] batch {attempts}: +{added} (total {len(got)}/{n})",
              file=sys.stderr)
        if added == 0 and attempts > 3:
            time.sleep(1)
    return got[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-course", type=int, default=0)
    ap.add_argument("--n-light", type=int, default=0)
    ap.add_argument("--n-preserve", type=int, default=0)
    ap.add_argument("--batch", type=int, default=25)
    ap.add_argument("--model", default=None)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--qc", action="store_true", help="Grok QC pass on course pairs")
    ap.add_argument("--avoid", type=Path, action="append", default=[],
                    help="JSON eval file(s) whose raw/clean must NOT appear")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    avoid: set[str] = set()
    for a in args.avoid:
        for it in json.loads(Path(a).read_text()):
            avoid.add(norm(it["raw"]))
            avoid.add(norm(it["clean"]))
    print(f"Avoid set: {len(avoid)} strings from {len(args.avoid)} file(s)",
          file=sys.stderr)

    pool_keys: set[str] = set()
    items: list[dict] = []
    for tag, n in (("course", args.n_course), ("light", args.n_light),
                   ("preserve", args.n_preserve)):
        if n > 0:
            print(f"\n=== generating {n} {tag} ===", file=sys.stderr)
            items += gen_bucket(tag, n, args.batch, args.model, rng, avoid, pool_keys)

    if args.qc:
        course = [it for it in items if it["tag"] == "course"]
        rest = [it for it in items if it["tag"] != "course"]
        print(f"\n=== QC on {len(course)} course pairs ===", file=sys.stderr)
        course_ok = qc_course(course, args.model)
        print(f"QC kept {len(course_ok)}/{len(course)} course", file=sys.stderr)
        items = course_ok + rest

    with args.out.open("w") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    tags: dict[str, int] = {}
    for it in items:
        tags[it["tag"]] = tags.get(it["tag"], 0) + 1
    print(f"\nWrote {len(items)} pairs -> {args.out}  {tags}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
