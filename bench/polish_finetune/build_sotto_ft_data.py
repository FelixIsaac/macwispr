#!/usr/bin/env python3
"""Build ~100+ synthetic pairs (expanded) for LoRA on Sotto LFM cleanup.

Uses Sotto native completion format (full text):
  ### Input:\\n{raw}\\n\\n### Output:\\n{clean}

Target: ~100 unique concepts → expanded surface variants for train stability.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = DATA / "sotto_ft"

# ---------------------------------------------------------------------------
# ~100 hand templates (course + light domain + preserve)
# ---------------------------------------------------------------------------

COURSE_PAIRS: list[tuple[str, str]] = [
    ("I wanna get the bag no not not not bag my phone", "I want to get my phone."),
    ("I wanna get my bag. No, no, not not bag, my phone.", "I want to get my phone."),
    ("we should use Qwen wait no use Parakeet V3", "We should use Parakeet V3."),
    ("ship version one point two point one no one point two point two", "Ship version 1.2.2."),
    ("open settings uh no open transcription settings", "Open transcription settings."),
    ("put the keys at the top no no put them at the bottom collapsed", "Put the keys at the bottom, collapsed."),
    (
        "download the one point two billion parameter model no the three hundred fifty million",
        "Download the 350 million parameter model.",
    ),
    ("Parquet V two no Parakeet V three for Europe", "Parakeet V3 for Europe."),
    ("send this to Slack wait no email instead", "Send this to email instead."),
    ("meet on Tuesday no Wednesday at three", "Meet on Wednesday at 3."),
    ("use the 1.2B model no the 350M model", "Use the 350M model."),
    ("buy milk no not milk eggs", "Buy eggs."),
    ("open main wait no open a branch", "Open a branch."),
    ("default to Qwen 0.6B no wait Qwen 1.7B on machines over sixteen gigabytes", "Default to Qwen 1.7B on machines over 16 GB."),
    ("hotkey is command space wait no option space", "Hotkey is Option Space."),
    ("enable telemetry no keep it opt in off by default", "Keep telemetry opt-in, off by default."),
    ("use Core ML for Qwen no for Parakeet", "Use Core ML for Parakeet."),
    ("banner under the notch no under the menu bar", "Banner under the menu bar."),
    ("call it Dynamic Island wait no just a menu bar banner", "Just a menu bar banner."),
    ("price it at fifteen dollars no free forever", "Price it free forever."),
    ("push to develop wait no main", "Push to main."),
    ("tag v1.2.1 wait no v1.2.2", "Tag v1.2.2."),
    ("model id aufklarer wait no mlx community", "Model id mlx-community."),
    ("WER target under five percent no under two", "WER target under two percent."),
    ("record sixteen kHz wait no forty eight then resample", "Record at 48 kHz then resample."),
    ("insert via clipboard only wait no accessibility paste", "Insert via Accessibility paste."),
    ("use hold mode only wait no support toggle too", "Support hold and toggle modes."),
    ("chime volume one hundred no soft ceiling", "Chime volume with a soft ceiling."),
    ("send transcripts to PostHog no never send transcripts", "Never send transcripts."),
    ("train on Switchboard wait no synthetic only for shipping", "Synthetic only for shipping."),
    ("I said bag wait phone", "I said phone."),
    ("use Kafka no RabbitMQ is simpler", "Use RabbitMQ; it is simpler."),
    ("deploy to staging no production", "Deploy to production."),
    ("meeting at 2 no 3 pm", "Meeting at 3 pm."),
    ("file a bug on GitLab no GitHub", "File a bug on GitHub."),
    ("assign to Alice no Bob", "Assign to Bob."),
    ("language English only no English and Asian via Qwen", "English and Asian via Qwen."),
    ("Parakeet for Chinese wait no Qwen for Chinese", "Qwen for Chinese."),
    ("latency target two seconds no under half a second", "Latency target under half a second."),
    ("bundle size under two gig no under five hundred meg is fine for models", "Under 500 MB is fine for models."),
]

LIGHT_PAIRS: list[tuple[str, str]] = [
    (
        "Maybe we can do a benchmark test to see which which model performs better",
        "Maybe we can do a benchmark test to see which model performs better.",
    ),
    (
        "um we need to uh update the models in the system itself",
        "We need to update the models in the system itself.",
    ),
    (
        "the listening banner is way too complicated too many words",
        "The listening banner is way too complicated — too many words.",
    ),
    (
        "we still need the LLM that does cleanup currently we haven't it",
        "We still need the LLM that does cleanup; currently we don't have it.",
    ),
    (
        "Parquet V two and V three there is not too much error rate difference",
        "Parakeet V2 and V3 do not have much error-rate difference.",
    ),
    (
        "Parakeet is more efficient it doesn't take five gigabytes of RAM",
        "Parakeet is more efficient; it doesn't take five gigabytes of RAM.",
    ),
    (
        "telemetry must stay opt-in and must never send transcript text or audio",
        "Telemetry must stay opt-in and must never send transcript text or audio.",
    ),
    (
        "the hotkey should be option space in hold mode with a soft chime",
        "The hotkey should be Option Space in hold mode with a soft chime.",
    ),
    (
        "if the machine has under sixteen gigabytes default to the zero point six B model",
        "If the machine has under sixteen gigabytes, default to the 0.6B model.",
    ),
    (
        "put bring your own key options at the bottom collapsed",
        "Put bring-your-own-key options at the bottom, collapsed.",
    ),
    (
        "uh i think we should focus on the er revenue numbers for Q3",
        "I think we should focus on the revenue numbers for Q3.",
    ),
    (
        "um the team is uh doing great but like we need more resources",
        "The team is doing great, but we need more resources.",
    ),
    (
        "so basically the graphql query is returning null for user data",
        "The GraphQL query is returning null for user data.",
    ),
    (
        "we are seeing some latency issues in production and we need to optimize database queries",
        "We are seeing some latency issues in production and we need to optimize database queries.",
    ),
    (
        "im gonna need more time for this rabbitmq migration",
        "I'm going to need more time for this RabbitMQ migration.",
    ),
    (
        "the the vlan configuration needs updating",
        "The VLAN configuration needs updating.",
    ),
    (
        "lets go ahead and optimize the tensorflow model for latency",
        "Let's go ahead and optimize the TensorFlow model for latency.",
    ),
    (
        "me and the ops team is investigating since monday",
        "The ops team and I have been investigating since Monday.",
    ),
    (
        "okay yeah right so basically ready to deploy",
        "Ready to deploy.",
    ),
    (
        "schedule a meeting for Tuesday at three and send the notes to the team",
        "Schedule a meeting for Tuesday at three and send the notes to the team.",
    ),
    (
        "please clean up this transcript and keep my original meaning",
        "Please clean up this transcript and keep my original meaning.",
    ),
    (
        "research how to launch on X LinkedIn and Product Hunt",
        "Research how to launch on X, LinkedIn, and Product Hunt.",
    ),
    (
        "use Grok Imagine for some video frames and update the images later",
        "Use Grok Imagine for some video frames and update the images later.",
    ),
    (
        "that that that way it's much more better",
        "That way it's much better.",
    ),
    (
        "as a as a baseline we can store previous dictations",
        "As a baseline we can store previous dictations.",
    ),
    (
        "i mean we could upgrade the nodes but uh thats not uh the real fix",
        "We could upgrade the nodes, but that's not the real fix.",
    ),
    (
        "the build failed on branch main wait no develop",
        "The build failed on develop.",
    ),
    (
        "configure the iot gateway with ipv4 hold on ipv6 addressing",
        "Configure the IoT gateway with IPv6 addressing.",
    ),
    (
        "set the timeout to ten seconds no hold on twenty seconds for the API call",
        "Set the timeout to twenty seconds for the API call.",
    ),
    (
        "goals for next quarter are one hit the nps target two cut costs three ship the app",
        "Goals for next quarter are: 1. Hit the NPS target 2. Cut costs 3. Ship the app.",
    ),
]

# Clean inputs that must stay almost unchanged (anti over-edit)
PRESERVE: list[str] = [
    "Ship it.",
    "Merge the pull request.",
    "Use Parakeet V3 for European languages.",
    "Qwen 1.7B is the default on machines with more than 16 GB of RAM.",
    "Never send transcript text through telemetry.",
    "Option Space starts and stops dictation.",
    "The listening banner shows a timer under the menu bar.",
    "MacWispr is free and runs fully on-device for local ASR.",
    "Download the polish model, about 300 MB.",
    "Hold mode starts on key down and stops on key up.",
]


def sotto_text(raw: str, clean: str) -> dict:
    return {
        "text": f"### Input:\n{raw.strip()}\n\n### Output:\n{clean.strip()}"
    }


def messify_light(clean: str, rng: random.Random) -> str:
    words = clean.strip().split()
    if len(words) < 4:
        return clean.lower().rstrip(".")
    fillers = ["um", "uh", "like", "you know", "I mean"]
    w = list(words)
    if rng.random() < 0.7:
        for _ in range(rng.randint(1, 2)):
            w.insert(rng.randint(0, len(w) - 1), rng.choice(fillers))
    if rng.random() < 0.4 and len(w) > 5:
        i = rng.randint(1, len(w) - 2)
        w.insert(i, w[i])
    text = " ".join(w)
    if rng.random() < 0.5:
        text = text[0].lower() + text[1:]
    text = re.sub(r"[.!?]+$", "", text)
    return text


def expand_course(raw: str, clean: str, rng: random.Random) -> list[tuple[str, str]]:
    out = [(raw, clean), (raw.lower(), clean)]
    prefixes = ["um ", "so ", "like ", "okay ", ""]
    for p in prefixes:
        if p:
            out.append((p + raw, clean))
    # stutter no
    if " no " in raw:
        out.append((raw.replace(" no ", " no no ", 1), clean))
        out.append((raw.replace(" no ", " wait no ", 1), clean))
    return out


def load_existing() -> list[tuple[str, str, str]]:
    """Load (raw, clean, tag) from repo seeds/teachers."""
    rows: list[tuple[str, str, str]] = []
    seed = DATA / "course_correction_seed.json"
    if seed.exists():
        for x in json.loads(seed.read_text()):
            if x.get("raw") and x.get("clean"):
                rows.append((x["raw"], x["clean"], "course"))
    for extra in ("course_correction_extra.json",):
        p = DATA / extra
        if p.exists():
            try:
                for x in json.loads(p.read_text()):
                    if x.get("raw") and x.get("clean"):
                        rows.append((x["raw"], x["clean"], "course"))
            except Exception:
                pass
    teacher = DATA / "teacher_pairs.jsonl"
    if teacher.exists():
        for line in teacher.read_text().splitlines():
            if not line.strip():
                continue
            m = json.loads(line)["messages"]
            raw, clean = m[1]["content"], m[2]["content"]
            rows.append((raw, clean, "light"))
    hist = ROOT.parent / "data" / "polish_history_sample.json"
    if hist.exists():
        # weak: use as light preserve-ish if short cleanup already in teacher
        pass
    return rows


def build(target_unique: int = 100, expand: bool = True, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    pairs: list[tuple[str, str, str]] = []

    for r, c in COURSE_PAIRS:
        pairs.append((r, c, "course"))
    for r, c in LIGHT_PAIRS:
        pairs.append((r, c, "light"))
    for c in PRESERVE:
        pairs.append((c, c, "preserve"))
        pairs.append((messify_light(c, rng), c, "preserve"))

    pairs.extend(load_existing())

    # Dedup by raw
    seen: set[str] = set()
    unique: list[tuple[str, str, str]] = []
    for r, c, t in pairs:
        key = r.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append((r.strip(), c.strip(), t))

    # If under target, synthesize more course swaps
    templates = [
        ("I want to buy {w} no not {w} {r}", "I want to buy {r}."),
        ("send this to {w} wait no {r}", "Send this to {r}."),
        ("use the {w} model no the {r} model", "Use the {r} model."),
        ("meet at {w} no {r}", "Meet at {r}."),
        ("open {w} wait no open {r}", "Open {r}."),
        ("ship {w} no {r}", "Ship {r}."),
        ("default to {w} wait no {r}", "Default to {r}."),
        ("call it {w} no {r}", "Call it {r}."),
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
        ("staging", "production"),
        ("Kafka", "RabbitMQ"),
        ("Command Space", "Option Space"),
        ("v1.2.1", "v1.2.2"),
        ("0.6B", "1.7B"),
        ("GitLab", "GitHub"),
        ("two seconds", "half a second"),
    ]
    i = 0
    while len(unique) < target_unique and i < 500:
        w, r = swaps[i % len(swaps)]
        tmpl_r, tmpl_c = templates[i % len(templates)]
        raw = tmpl_r.format(w=w, r=r)
        clean = tmpl_c.format(w=w, r=r)
        key = raw.lower()
        if key not in seen:
            seen.add(key)
            unique.append((raw, clean, "course"))
        i += 1

    unique = unique[: max(target_unique, len(unique))]
    # Cap unique around target for reporting; still expand variants below
    if len(unique) > target_unique + 40:
        # keep diversity: shuffle and take target + extras for domain
        rng.shuffle(unique)
        # prefer keeping all course from hand list — already first

    rows: list[dict] = []
    for r, c, t in unique:
        if expand and t == "course":
            for rr, cc in expand_course(r, c, rng):
                rows.append(sotto_text(rr, cc))
        else:
            rows.append(sotto_text(r, c))
        if expand and t == "light" and rng.random() < 0.5:
            rows.append(sotto_text(messify_light(c, rng), c))
        if t == "preserve":
            rows.append(sotto_text(r, c))

    # Dedup text rows
    seen_t: set[str] = set()
    final: list[dict] = []
    for row in rows:
        if row["text"] in seen_t:
            continue
        seen_t.add(row["text"])
        final.append(row)

    rng.shuffle(final)
    return final, unique


def write_splits(rows: list[dict], out_dir: Path, seed: int = 42) -> None:
    rng = random.Random(seed)
    rng.shuffle(rows)
    n = len(rows)
    n_test = max(8, int(n * 0.06))
    n_valid = max(12, int(n * 0.1))
    test, valid, train = rows[:n_test], rows[n_test : n_test + n_valid], rows[n_test + n_valid :]
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, part in ("train", train), ("valid", valid), ("test", test):
        path = out_dir / f"{name}.jsonl"
        with path.open("w") as f:
            for r in part:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{name}: {len(part)} -> {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unique", type=int, default=100, help="Target unique seed pairs")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-expand", action="store_true")
    args = ap.parse_args()

    rows, unique = build(target_unique=args.unique, expand=not args.no_expand, seed=args.seed)
    print(f"Unique concepts: {len(unique)}")
    print(f"Expanded rows:   {len(rows)}")
    write_splits(rows, args.out, seed=args.seed)
    meta = {
        "unique": len(unique),
        "rows": len(rows),
        "format": "sotto_text_###_input_output",
        "unique_tags": {},
    }
    for _, _, t in unique:
        meta["unique_tags"][t] = meta["unique_tags"].get(t, 0) + 1
    (args.out / "meta.json").write_text(json.dumps(meta, indent=2))
    print("meta:", meta)


if __name__ == "__main__":
    main()
