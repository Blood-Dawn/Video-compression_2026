"""Stamp one version into the three files that must agree on release day.

    python scripts/stamp_release_version.py v2.2.4-beta
    python scripts/stamp_release_version.py 2.2.5.dev0 --check

The installer, pyproject.toml and src/utils/version.py each carry the version.
A release built while they still said "2.2.1.dev0" shipped an installer that
reported itself as older than its own v2.2.1-beta tag, so a fresh install
offered an update to the version it already had (issue #20).

Tags use the GitHub shape (v2.2.4-beta); pyproject.toml wants PEP 440
(2.2.4b0). The installer and APP_VERSION keep the tag spelling so the in-app
update check compares like with like.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAG_RE = re.compile(r"^v?(\d+\.\d+\.\d+)(?:[.\-]?(dev|alpha|a|beta|b|rc)(\d*))?$")
PEP440_STAGE = {"dev": ".dev", "alpha": "a", "a": "a", "beta": "b", "b": "b", "rc": "rc"}

TARGETS = (
    (
        "pyproject.toml",
        re.compile(r'^(version\s*=\s*")[^"]+(")', re.M),
        "pep440",
    ),
    (
        "installer/svcs.iss",
        re.compile(r'^(#define\s+MyAppVersion\s+")[^"]+(")', re.M),
        "tag",
    ),
    (
        "src/utils/version.py",
        re.compile(r'^(APP_VERSION\s*=\s*")[^"]+(")', re.M),
        "tag",
    ),
)


def spellings(raw: str) -> dict[str, str]:
    m = TAG_RE.match(raw.strip())
    if not m:
        raise ValueError(f"not a version this project uses: {raw!r}")
    base, stage, num = m.groups()
    if not stage:
        return {"tag": base, "pep440": base}
    tag = f"{base}-{stage}" if stage not in ("dev",) else f"{base}.dev{num or 0}"
    pep = f"{base}{PEP440_STAGE[stage]}{num or 0}"
    return {"tag": tag, "pep440": pep}


def stamp(raw: str, root: Path = ROOT, check: bool = False) -> list[str]:
    """Rewrite the three files. Returns the files that differ (or changed)."""
    forms = spellings(raw)
    changed = []
    for rel, pattern, kind in TARGETS:
        path = root / rel
        text = path.read_bytes().decode("utf-8")
        new, n = pattern.subn(lambda m: m.group(1) + forms[kind] + m.group(2), text, count=1)
        if n != 1:
            raise RuntimeError(f"version line not found in {rel}")
        if new != text:
            changed.append(rel)
            if not check:
                path.write_bytes(new.encode("utf-8"))
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version", help="release tag or version, e.g. v2.2.4-beta")
    ap.add_argument("--check", action="store_true", help="exit 1 if any file differs, change nothing")
    args = ap.parse_args(argv)
    try:
        changed = stamp(args.version, check=args.check)
    except (ValueError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 2
    for rel in changed:
        print(("differs: " if args.check else "stamped: ") + rel)
    if not changed:
        print("already stamped")
    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
