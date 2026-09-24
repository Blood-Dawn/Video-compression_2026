#!/usr/bin/env python3
"""
scripts/check_doc_links.py - report broken relative links in Markdown files.

Why: docs moved around a lot during 2026 (canonical docs at docs/ root,
records under docs/<topic>/, mobile docs under mobile/android/), and a moved
file silently breaks every relative link that pointed at it. This walks every
tracked *.md file, resolves each relative Markdown link and each backticked
repo path that looks like a file (`docs/...`, `mobile/...`, `src/...`), and
prints the ones that do not exist. External URLs and #anchors are skipped.

Usage:
    python scripts/check_doc_links.py            # all tracked Markdown
    python scripts/check_doc_links.py --links    # Markdown links only

Exit code is 1 when anything is broken, so it can gate CI later.

Author: Bloodawn (KheivenD), 2026-09-24 (repo cleanup sweep).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# [text](target) and ![alt](target); the target stops at whitespace or ")".
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
# `docs/foo.md`, `mobile/android/README.md`: repo-rooted paths in backticks.
CODE_PATH_RE = re.compile(
    r"`((?:docs|mobile|src|scripts|installer|tests)/[A-Za-z0-9_./-]+\.[A-Za-z0-9]+)`"
)

# Dated records quote paths as they were at the time; they are history, not
# navigation, so their backticked paths are not checked (links still are).
HISTORY_DIRS = ("docs/archive/", "docs/project-records/", "docs/plans/")


def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    return [ROOT / p for p in out]


def check(md: Path, links_only: bool) -> list[str]:
    rel_md = md.relative_to(ROOT).as_posix()
    text = md.read_text(encoding="utf-8", errors="replace")
    problems = []
    for m in LINK_RE.finditer(text):
        target = m.group(1)
        if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            continue
        path = target.split("#", 1)[0]
        if not path:
            continue
        resolved = (md.parent / path).resolve()
        if not resolved.exists():
            problems.append(f"{rel_md}: link -> {target}")
    if links_only or rel_md.startswith(HISTORY_DIRS):
        return problems
    for m in CODE_PATH_RE.finditer(text):
        path = m.group(1)
        if "<" in path or "*" in path:
            continue
        if not (ROOT / path).exists():
            problems.append(f"{rel_md}: path `{path}`")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--links", action="store_true", help="only check Markdown links")
    args = ap.parse_args()
    problems = []
    for md in tracked_markdown():
        problems.extend(check(md, args.links))
    for p in problems:
        print(p)
    print(f"{len(problems)} broken reference(s)", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
