"""Complexity ratchet: fail on new or worsened high-complexity functions.

Runs radon over src/ and compares every function above THRESHOLD against
scripts/complexity_baseline.json. A function fails the check when it is above
THRESHOLD and either is not in the baseline or scores higher than its
baseline value. Functions that improve are reported so the baseline can be
lowered with --update. The baseline never grows silently: --update refuses to
add a function or raise a value unless --allow-worse is given.

Usage:
    python scripts/complexity_ratchet.py            # check (CI)
    python scripts/complexity_ratchet.py --update   # lower/remove entries

Needs radon (CI-only tool, not a project dependency).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THRESHOLD = 15  # radon grade C tops out at 20; gate new code at 15
ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "complexity_baseline.json"


def measure(src: Path = ROOT / "src") -> dict[str, int]:
    """Return {"path::qualname": complexity} for functions above THRESHOLD."""
    from radon.complexity import cc_visit

    found: dict[str, int] = {}
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        try:
            blocks = cc_visit(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            print(f"skip {rel}: {exc}", file=sys.stderr)
            continue
        for block in blocks:
            if block.complexity <= THRESHOLD:
                continue
            owner = getattr(block, "classname", None)
            name = f"{owner}.{block.name}" if owner else block.name
            key = f"{rel}::{name}"
            found[key] = max(found.get(key, 0), block.complexity)
    return found


def compare(found: dict[str, int], baseline: dict[str, int]):
    """Return (worse, improved, gone) lists of (key, now, was)."""
    worse = [(k, v, baseline.get(k)) for k, v in found.items()
             if k not in baseline or v > baseline[k]]
    improved = [(k, v, baseline[k]) for k, v in found.items()
                if k in baseline and v < baseline[k]]
    gone = [(k, None, v) for k, v in baseline.items() if k not in found]
    return worse, improved, gone


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update", action="store_true",
                        help="rewrite the baseline with lower values")
    parser.add_argument("--allow-worse", action="store_true",
                        help="with --update, also accept new or higher entries")
    args = parser.parse_args(argv)

    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    found = measure()
    worse, improved, gone = compare(found, baseline)

    for key, now, was in worse:
        was_txt = "not in baseline" if was is None else f"baseline {was}"
        print(f"WORSE    {key}: {now} ({was_txt})")
    for key, now, was in improved:
        print(f"improved {key}: {now} (baseline {was}), run --update to lock in")
    for key, _now, was in gone:
        print(f"gone     {key} (baseline {was}), run --update to remove")

    if args.update:
        if worse and not args.allow_worse:
            print("refusing to update: some functions got worse", file=sys.stderr)
            return 1
        BASELINE.write_text(json.dumps(dict(sorted(found.items())), indent=2) + "\n",
                            encoding="utf-8")
        print(f"baseline written: {len(found)} functions")
        return 0

    if worse:
        print(f"\n{len(worse)} function(s) above complexity {THRESHOLD} are new or worse.")
        return 1
    print(f"ok: {len(found)} baseline function(s) above {THRESHOLD}, none worse")
    return 0


if __name__ == "__main__":
    sys.exit(main())
