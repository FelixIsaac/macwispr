#!/usr/bin/env python3
"""Build train/valid/test.jsonl for dictation-polish LoRA (mlx-lm chat format)."""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

SYSTEM = (
    "Clean this voice dictation for typing into an app. "
    "Keep every idea the speaker said; do not summarize. "
    "Remove stutters, repeated words, and fillers. "
    "Fix light grammar, punctuation, and capitalization. "
    "Output only the cleaned text."
)

FILLERS = ["um", "uh", "like", "you know", "I mean", "basically", "actually", "so"]
ASR_SWAPS = [
    ("Parakeet", "Parquet"),
    ("Qwen", "Quen"),
    ("Qwen", "Quan"),
    ("0.6B", "zero point six B"),
    ("1.7B", "one point seven B"),
    ("16 GB", "sixteen GB"),
]


def word_count(s: str) -> int:
    return len(s.split())


def ok_pair(raw: str, clean: str) -> bool:
    raw, clean = raw.strip(), clean.strip()
    if not raw or not clean:
        return False
    rw, cw = word_count(raw), word_count(clean)
    if rw < 3 or cw < 2:
        return False
    if cw < max(3, int(rw * 0.4)):
        return False
    if cw > max(rw * 2.5, rw + 40):
        return False
    bad = ("i'm sorry", "as an ai", "i cannot", "i can't help")
    if any(b in clean.lower() for b in bad):
        return False
    return True


def messify(clean: str, rng: random.Random) -> str:
    """Inject spoken / ASR-like noise into clean text."""
    text = clean.strip()
    words = text.split()
    if len(words) < 4:
        return text

    # fillers
    if rng.random() < 0.7:
        for _ in range(rng.randint(1, 3)):
            i = rng.randint(0, len(words) - 1)
            words.insert(i, rng.choice(FILLERS) + rng.choice(["", ",", ""]))

    # word repeats
    if rng.random() < 0.55 and len(words) > 5:
        i = rng.randint(1, len(words) - 2)
        w = re.sub(r"[^\w']", "", words[i])
        if w and len(w) > 2:
            words[i:i] = [words[i]] * rng.randint(1, 2)

    text = " ".join(words)

    # false start
    if rng.random() < 0.35:
        head = " ".join(text.split()[: rng.randint(2, min(5, len(text.split())))])
        text = f"{head}, wait, {text}"

    # spoken style punct
    if rng.random() < 0.4:
        text = text[0].lower() + text[1:] if text else text
    if rng.random() < 0.25:
        text = re.sub(r"\?$", " ?", text)
    if rng.random() < 0.2:
        text = text.replace(". ", ", ")

    # ASR swaps
    for a, b in ASR_SWAPS:
        if a in text and rng.random() < 0.35:
            text = text.replace(a, b, 1)

    # double spaces / that that
    text = re.sub(r"\s+", " ", text).strip()
    return text


def pair_messages(raw: str, clean: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": raw.strip()},
            {"role": "assistant", "content": clean.strip()},
        ]
    }


def seed_clean_sentences() -> list[str]:
    """Domain-ish clean targets for synthetic generation."""
    base = [
        "Maybe we can run a benchmark to see which model performs better.",
        "If we store the audio from previous dictations, we can use that as a baseline for cleanup tests.",
        "We might need to train our own MLX Gemma three 270 million parameter model so the output is better.",
        "Update the models in the system and reduce the number of settings so the UI is less cluttered.",
        "Put bring-your-own-key options at the bottom, collapsed, so they do not clutter the UI.",
        "Give users Parakeet V2 by default; they can switch to V3. Only use Qwen when they need Chinese.",
        "It will track more data: their name, words per minute, and usage frequency, so they must opt in.",
        "The listening banner is too complicated; show only a glowing red dot and a number.",
        "Research how to launch on X, LinkedIn, and Product Hunt, and prepare this folder without pushing to main.",
        "We still need the LLM that does cleanup. Check how Wispr Flow and FluidVoice handle it.",
        "There is not much WER difference between Parakeet V2 and V3; use V3 for EU languages and Qwen3 ASR for Asian languages.",
        "Use Grok Imagine for some video frames and update the images in the repo later.",
        "Parakeet is more efficient; it does not take five gigabytes of RAM, and system memory use looks like only a few hundred megabytes.",
        "The UI glitches while speaking, scaling up and down; make it translucent and drop the blinking dots.",
        "This does not follow Apple HIG; it looks taped on rather than integrated with the Mac shape.",
        "If the machine has under sixteen gigabytes of memory, default to the zero point six B model.",
        "Please clean up this transcript and keep my original meaning.",
        "Schedule a meeting for Tuesday at three and send the notes to the team.",
        "The hotkey should be Option Space in hold mode, with a soft chime on start and stop.",
        "Telemetry must stay opt-in and must never send transcript text or audio.",
    ]
    # Expand by light paraphrases
    extra = []
    for s in base:
        extra.append(s)
        if s.endswith("."):
            extra.append(s[:-1] + " please.")
    return extra


def from_history(path: Path, rng: random.Random) -> list[dict]:
    """Use history text as raw; synthesize a mild clean target via light rules (teacher-weak)."""
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    out = []
    for e in data:
        raw = (e.get("text") or "").strip()
        if word_count(raw) < 8:
            continue
        # Weak clean: collapse exact immediate repeats, fix spaces, capitalize
        clean = re.sub(r"\b(\w+)(?:\s+\1){1,3}\b", r"\1", raw, flags=re.I)
        clean = re.sub(r"\s+", " ", clean).strip()
        if clean:
            clean = clean[0].upper() + clean[1:]
        # Only keep if we actually changed something lightly
        if clean == raw:
            # still train identity sometimes so model doesn't always rewrite
            if rng.random() < 0.3 and ok_pair(raw, clean):
                out.append(pair_messages(raw, clean))
            continue
        if ok_pair(raw, clean):
            out.append(pair_messages(raw, clean))
    return out


def try_hf_cleanup(limit: int, rng: random.Random) -> list[dict]:
    try:
        from datasets import load_dataset
    except ImportError:
        return []
    pairs = []
    try:
        ds = load_dataset("danielrosehill/Transcription-Cleanup-Trainer")
        split = ds["train"] if "train" in ds else ds[list(ds.keys())[0]]
        cols = split.column_names
        # flexible column names for true pairs
        raw_keys = [c for c in cols if re.search(r"raw|messy|source|input|original", c, re.I)]
        clean_keys = [c for c in cols if re.search(r"clean|gold|target|output|fixed", c, re.I)]
        if raw_keys and clean_keys:
            rk, ck = raw_keys[0], clean_keys[0]
            idxs = list(range(len(split)))
            rng.shuffle(idxs)
            for i in idxs:
                if len(pairs) >= limit:
                    break
                row = split[i]
                raw, clean = str(row[rk]), str(row[ck])
                if ok_pair(raw, clean):
                    pairs.append(pair_messages(raw, clean))
        elif "text" in cols:
            # Clean-only: synthesize messy inputs from gold text
            for row in split:
                if len(pairs) >= limit:
                    break
                clean = str(row["text"]).strip()
                if word_count(clean) < 8:
                    continue
                raw = messify(clean, rng)
                if ok_pair(raw, clean):
                    pairs.append(pair_messages(raw, clean))
        elif len(cols) >= 2:
            rk, ck = cols[0], cols[1]
            for row in split:
                if len(pairs) >= limit:
                    break
                raw, clean = str(row[rk]), str(row[ck])
                if ok_pair(raw, clean):
                    pairs.append(pair_messages(raw, clean))
    except Exception as e:
        print(f"HF dataset skipped: {e}")
    return pairs


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=Path(__file__).parent / "data")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--synthetic", type=int, default=800)
    ap.add_argument("--hf-limit", type=int, default=400)
    ap.add_argument(
        "--history",
        type=Path,
        default=Path.home() / "Library/Application Support/MacWispr/history.json",
    )
    ap.add_argument("--valid-frac", type=float, default=0.08)
    ap.add_argument("--test-frac", type=float, default=0.05)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    pairs: list[dict] = []

    # Synthetic
    cleans = seed_clean_sentences()
    for _ in range(args.synthetic):
        clean = rng.choice(cleans)
        # slight clean variation
        if rng.random() < 0.2:
            clean = clean.replace(" we ", " you ").replace("We ", "You ")
        raw = messify(clean, rng)
        if ok_pair(raw, clean):
            pairs.append(pair_messages(raw, clean))

    # History-derived
    hist = from_history(args.history, rng)
    pairs.extend(hist)
    print(f"history pairs: {len(hist)}")

    # HF public
    hf = try_hf_cleanup(args.hf_limit, rng)
    pairs.extend(hf)
    print(f"HF pairs: {len(hf)}")

    # Dedup by raw
    seen = set()
    uniq = []
    for p in pairs:
        raw = p["messages"][1]["content"]
        if raw in seen:
            continue
        seen.add(raw)
        uniq.append(p)
    pairs = uniq
    rng.shuffle(pairs)

    n = len(pairs)
    n_test = max(1, int(n * args.test_frac))
    n_valid = max(1, int(n * args.valid_frac))
    test = pairs[:n_test]
    valid = pairs[n_test : n_test + n_valid]
    train = pairs[n_test + n_valid :]

    write_jsonl(args.out_dir / "train.jsonl", train)
    write_jsonl(args.out_dir / "valid.jsonl", valid)
    write_jsonl(args.out_dir / "test.jsonl", test)

    print(f"Wrote {len(train)} train / {len(valid)} valid / {len(test)} test → {args.out_dir}")
    print(f"Total unique pairs: {n}")
    if train:
        print("Sample train row:")
        print(json.dumps(train[0], indent=2)[:500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
