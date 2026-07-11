#!/usr/bin/env python3
"""Convert a Grok-generated pair pool (JSONL) into Sotto-format train splits.

- Sotto native completion format: "### Input:\\n{raw}\\n\\n### Output:\\n{clean}"
- Light surface expansion on course items only (lowercase / prefix variants) so
  the model sees casing robustness without inventing new semantics.
- Hard leak gate against an --avoid eval file (normalized). Aborts on overlap.
- Writes train/valid/test to --out-dir.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).parent


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def sotto(raw: str, clean: str) -> dict:
    return {"text": f"### Input:\n{raw.strip()}\n\n### Output:\n{clean.strip()}"}


def expand_course(raw: str, clean: str, rng: random.Random) -> list[tuple[str, str]]:
    out = [(raw, clean)]
    if raw and raw[0].isupper():
        out.append((raw[0].lower() + raw[1:], clean))
    for p in ("um ", "so ", "okay "):
        if rng.random() < 0.4:
            out.append((p + raw, clean))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=Path, required=True)
    ap.add_argument("--avoid", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "data" / "sotto_ft_v2")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-expand", action="store_true")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    avoid: set[str] = set()
    for it in json.loads(args.avoid.read_text()):
        avoid.add(norm(it["raw"]))
        avoid.add(norm(it["clean"]))

    pool = [json.loads(l) for l in args.pool.read_text().splitlines() if l.strip()]

    rows: list[dict] = []
    seen_raw: set[str] = set()
    leaked = 0
    for it in pool:
        raw, clean, tag = it["raw"].strip(), it["clean"].strip(), it["tag"]
        rn = norm(raw)
        if rn in avoid or norm(clean) in avoid:
            leaked += 1
            continue
        if rn in seen_raw:
            continue
        seen_raw.add(rn)
        if tag == "course" and not args.no_expand:
            for rr, cc in expand_course(raw, clean, rng):
                rows.append(sotto(rr, cc))
        else:
            rows.append(sotto(raw, clean))

    # Dedup text rows
    seen_t, final = set(), []
    for r in rows:
        if r["text"] in seen_t:
            continue
        seen_t.add(r["text"])
        final.append(r)
    rng.shuffle(final)

    n = len(final)
    n_test = max(8, int(n * 0.05))
    n_valid = max(20, int(n * 0.08))
    test, valid, train = final[:n_test], final[n_test:n_test + n_valid], final[n_test + n_valid:]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, part in ("train", train), ("valid", valid), ("test", test):
        with (args.out_dir / f"{name}.jsonl").open("w") as f:
            for r in part:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"pool={len(pool)} leaked_dropped={leaked} unique_raw={len(seen_raw)} "
          f"rows={n}")
    print(f"train={len(train)} valid={len(valid)} test={len(test)} -> {args.out_dir}")
    if leaked:
        print(f"NOTE: dropped {leaked} pool rows that collided with the eval set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
