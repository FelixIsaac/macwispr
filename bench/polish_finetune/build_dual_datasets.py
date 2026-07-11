#!/usr/bin/env python3
"""Build two polish datasets: light vs smart (course-correction)."""

from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"

SYS_LIGHT = (
    "Clean this voice dictation lightly for typing into an app. "
    "Keep every idea and almost all wording. "
    "Remove only stutters, repeated words, and fillers. "
    "Fix light grammar, punctuation, and capitalization. "
    "Do not rewrite meaning or drop clauses. "
    "Output only the cleaned text."
)

SYS_SMART = (
    "Clean this voice dictation into what the speaker finally meant. "
    "Apply spoken self-corrections: if they say X then correct to Y "
    "(e.g. 'the bag no not bag my phone'), keep only the final intent. "
    "Drop abandoned false starts, 'wait', 'no not X', and stutters. "
    "Do not summarize away separate final requests. "
    "Output only the cleaned text."
)


def messages(system: str, raw: str, clean: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": raw.strip()},
            {"role": "assistant", "content": clean.strip()},
        ]
    }


def write_split(dir_path: Path, rows: list[dict], seed: int = 0) -> None:
    rng = random.Random(seed)
    rng.shuffle(rows)
    n = len(rows)
    n_test = max(4, int(n * 0.06))
    n_valid = max(8, int(n * 0.1))
    test, valid, train = rows[:n_test], rows[n_test : n_test + n_valid], rows[n_test + n_valid :]
    dir_path.mkdir(parents=True, exist_ok=True)
    for name, part in ("train", train), ("valid", valid), ("test", test):
        with (dir_path / f"{name}.jsonl").open("w") as f:
            for r in part:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{dir_path.name}: train={len(train)} valid={len(valid)} test={len(test)}")


def expand_course(seed_rows: list[dict], rng: random.Random) -> list[dict]:
    """More surface variants of course-correction pairs."""
    out = []
    prefixes = ["um ", "so ", "like ", "okay ", ""]
    for row in seed_rows:
        raw, clean = row["raw"], row["clean"]
        out.append(messages(SYS_SMART, raw, clean))
        # slight raw noise
        for _ in range(2):
            r = rng.choice(prefixes) + raw
            r = r.replace(" no ", " no no ").replace(" wait ", " wait wait ", 1)
            out.append(messages(SYS_SMART, r, clean))
    # extra template family: want X no Y
    templates = [
        (
            "I want to buy {wrong} no not {wrong} {right}",
            "I want to buy {right}.",
        ),
        (
            "send this to {wrong} wait no {right}",
            "Send this to {right}.",
        ),
        (
            "use the {wrong} model no the {right} model",
            "Use the {right} model.",
        ),
        (
            "meet at {wrong} no {right}",
            "Meet at {right}.",
        ),
    ]
    swaps = [
        ("bag", "phone"),
        ("milk", "eggs"),
        ("Qwen", "Parakeet"),
        ("1.2B", "350M"),
        ("Tuesday", "Wednesday"),
        ("Slack", "email"),
        ("main", "a branch"),
        ("loud", "soft"),
    ]
    for wrong, right in swaps:
        for raw_t, clean_t in templates:
            raw = raw_t.format(wrong=wrong, right=right)
            clean = clean_t.format(wrong=wrong, right=right)
            out.append(messages(SYS_SMART, raw, clean))
            out.append(messages(SYS_SMART, raw.lower(), clean))
    return out


def main() -> None:
    rng = random.Random(11)

    # --- LIGHT: teacher history + optional seed ---
    light: list[dict] = []
    teacher_path = DATA / "teacher_pairs.jsonl"
    if teacher_path.exists():
        for line in teacher_path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            # re-stamp system as light
            raw = row["messages"][1]["content"]
            clean = row["messages"][2]["content"]
            light.append(messages(SYS_LIGHT, raw, clean))
            # identity-ish: already clean dictation should stay similar
            if rng.random() < 0.2:
                light.append(messages(SYS_LIGHT, clean, clean))

    write_split(DATA / "light", light, seed=11)

    # --- SMART: course correction ---
    seed = json.loads((DATA / "course_correction_seed.json").read_text())
    # merge subagent outputs if present
    for extra in ("course_correction_extra.json", "light_polish_extra.json"):
        p = DATA / extra
        if p.exists():
            try:
                arr = json.loads(p.read_text())
                if extra.startswith("course"):
                    seed.extend([x for x in arr if x.get("raw") and x.get("clean")])
                else:
                    for x in arr:
                        if x.get("raw") and x.get("clean"):
                            light.append(messages(SYS_LIGHT, x["raw"], x["clean"]))
            except Exception as e:
                print("skip", extra, e)

    smart = expand_course(seed, rng)
    # Also teach smart model light cases so it doesn't always over-edit short clean text
    for row in light[:40]:
        raw = row["messages"][1]["content"]
        clean = row["messages"][2]["content"]
        # only if raw has no obvious correction markers
        if not any(k in raw.lower() for k in (" no not", " wait", " i mean ", " no no")):
            smart.append(messages(SYS_SMART, raw, clean))

    write_split(DATA / "smart", smart, seed=22)

    # Save prompts for app wiring later
    (DATA / "prompts.json").write_text(
        json.dumps({"light": SYS_LIGHT, "smart": SYS_SMART}, indent=2)
    )
    print("Wrote prompts.json + light/ + smart/ datasets")


if __name__ == "__main__":
    main()
