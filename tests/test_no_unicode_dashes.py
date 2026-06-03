"""
tests/test_no_unicode_dashes.py

Guard for FIX 9: no em dash (U+2014) or en dash (U+2013) may appear in tracked
text files. They were swept to ASCII; this test fails if any creep back, so the
rule stays enforced. The forbidden characters are referenced via escape
sequences so this file does not trip its own check.

Author: Bloodawn (KheivenD), 2026-06-03 (FIX 9).
"""

import os
from pathlib import Path

ROOT = Path(__file__).parent.parent

EM = chr(0x2014)  # em dash, built by code so this file stays clean
EN = chr(0x2013)  # en dash

# Text extensions to scan. Binary assets are skipped by extension.
EXTS = {".py", ".js", ".html", ".css", ".md", ".txt", ".iss",
        ".ps1", ".sh", ".yml", ".yaml", ".toml"}

# Directories that are scanned for the guard.
SCAN_DIRS = ["src", "tests", "docs", "installer", "scripts", ".github"]

# Directories never descended into.
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build",
             ".pytest_tmp", "logs", "tools", "data", "__pycache__"}


def _iter_text_files():
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS]
            for f in filenames:
                if os.path.splitext(f)[1].lower() in EXTS:
                    yield Path(dirpath) / f
    for f in ROOT.glob("*.md"):
        yield f


def test_no_em_or_en_dashes_anywhere():
    offenders = []
    for p in _iter_text_files():
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if EM in text or EN in text:
            offenders.append(str(p.relative_to(ROOT)))
    assert not offenders, (
        "Em/en dashes found (use ASCII hyphen instead) in:\n" + "\n".join(offenders))


def test_src_tree_is_clean():
    # The hard requirement: the shipping source tree has none.
    bad = []
    for dirpath, dirnames, filenames in os.walk(ROOT / "src"):
        dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS]
        for f in filenames:
            if os.path.splitext(f)[1].lower() in EXTS:
                p = Path(dirpath) / f
                t = p.read_text(encoding="utf-8", errors="replace")
                if EM in t or EN in t:
                    bad.append(str(p.relative_to(ROOT)))
    assert not bad, bad
