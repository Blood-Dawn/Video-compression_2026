"""
tests/test_no_unicode_dashes.py

Guard for FIX 9: no em dash (U+2014) or en dash (U+2013) may appear in tracked
text files. They were swept to ASCII; this test fails if any creep back, so the
rule stays enforced. The forbidden characters are referenced via escape
sequences so this file does not trip its own check.

Scope note (2026-07-18). The walk had three blind spots, all of the same shape:
a file could violate the rule while this test reported clean.

  1. Root level saw ``*.md`` ONLY, so every root-level script was invisible.
     run_gui.py, demo.sh, check_deps.sh, start.ps1, docker-compose.yml and
     pyproject.toml had accumulated 37 em dashes between them. Several were in
     strings the shell scripts PRINT, so the rule was being broken in
     user-facing output.
  2. Extension-keyed matching cannot see files that HAVE no extension.
     Dockerfile (shipped code) and installer/appimage/AppRun (a shell script)
     were both unguarded.
  3. ``.spec`` was absent from EXTS, so installer/svcs.spec, which is real
     Python driving the PyInstaller build, was never scanned.

A guard that silently misses a whole class of file is worse than no guard,
because it makes the rule look enforced when it is not. The scope tests below
exist so these gaps cannot reopen quietly.

Deliberately still out of scope: untracked scratch files, and any vendored
third-party tree (a backup venv under site-packages carries plenty of em
dashes; those are not ours to edit).

Author: Bloodawn (KheivenD), 2026-06-03 (FIX 9).
Updated:  Bloodawn (KheivenD), 2026-07-18 (close the three scope gaps).
"""

import os
from pathlib import Path

ROOT = Path(__file__).parent.parent

EM = chr(0x2014)  # em dash, built by code so this file stays clean
EN = chr(0x2013)  # en dash

# Text extensions to scan. Binary assets are skipped by extension.
EXTS = {".py", ".js", ".html", ".css", ".md", ".txt", ".iss",
        ".ps1", ".sh", ".yml", ".yaml", ".toml", ".kt", ".kts", ".xml",
        ".pro", ".cfg", ".ini", ".spec", ".dockerfile", ".properties", ".bat"}

# Text files that carry NO extension, matched by exact name. Dockerfile is
# shipped code and the dot-files carry comments, so the rule applies to them
# just as much, but an extension-keyed scan can never see them.
EXTENSIONLESS_NAMES = {
    "Dockerfile", ".dockerignore", ".gitattributes", ".gitignore",
    ".editorconfig", "Makefile", "AppRun",
    # Gradle wrapper launcher: generated, extensionless, and committed.
    "gradlew",
}

# Directories that are scanned for the guard.
# "mobile" carries the Android module and the imported design tokens; both are
# product surface and both are covered.
SCAN_DIRS = ["src", "tests", "docs", "installer", "scripts", ".github", "mobile"]

# Directories never descended into. ".gradle", ".idea" and ".cxx" are Android
# build caches: adding "mobile" to SCAN_DIRS without them made this test walk
# tens of thousands of generated files and took it from 0.3s to 4s.
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build",
             ".pytest_tmp", "logs", "tools", "data", "__pycache__",
             ".gradle", ".idea", ".cxx", ".kotlin"}


def _iter_text_files():
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS]
            for f in filenames:
                if (os.path.splitext(f)[1].lower() in EXTS
                        or f in EXTENSIONLESS_NAMES):
                    yield Path(dirpath) / f
    # Root-level files of EVERY scanned extension, not just *.md.
    #
    # This used to glob "*.md" only, which left every root-level script
    # unguarded: run_gui.py, demo.sh, check_deps.sh, start.ps1,
    # docker-compose.yml and pyproject.toml between them had accumulated 37
    # em dashes by 2026-07-18. Several were in strings the shell scripts PRINT,
    # so the rule was being broken in user-facing output while the guard
    # reported clean, which is worse than having no guard.
    for f in sorted(ROOT.glob("*")):
        if not f.is_file():
            continue
        if f.suffix.lower() in EXTS or f.name in EXTENSIONLESS_NAMES:
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


def _scanned():
    """The set of repo-relative paths the guard actually looks at."""
    return {str(p.relative_to(ROOT)).replace("\\", "/") for p in _iter_text_files()}


# ── scope guards ─────────────────────────────────────────────────────────────
# The original defect was not a missed dash, it was a missed DIRECTORY LEVEL:
# the walk covered SCAN_DIRS plus root-level *.md, so every root-level script
# was invisible and 37 em dashes accumulated there while this file reported
# clean. These tests pin the scope so that cannot happen silently again.

def test_root_level_python_files_are_scanned():
    scanned = _scanned()
    root_py = {p.name for p in ROOT.glob("*.py")}
    assert root_py, "expected at least one root-level .py file"
    missing = root_py - scanned
    assert not missing, f"root-level Python files are not guarded: {sorted(missing)}"


def test_root_level_scripts_are_scanned():
    """Shell and PowerShell scripts at the root print to the user."""
    scanned = _scanned()
    for pattern in ("*.sh", "*.ps1", "*.toml", "*.yml"):
        for f in ROOT.glob(pattern):
            assert f.name in scanned, f"{f.name} is not guarded"


def test_extensionless_root_files_are_scanned():
    """Dockerfile is shipped code; an extension-keyed scan cannot see it."""
    scanned = _scanned()
    for name in EXTENSIONLESS_NAMES:
        if (ROOT / name).is_file():
            assert name in scanned, f"{name} exists but is not guarded"


def test_mobile_module_is_scanned():
    """The Android module and the imported design tokens are product surface."""
    mobile = ROOT / "mobile"
    if not mobile.is_dir():
        return
    scanned = _scanned()
    kotlin = [p for p in mobile.rglob("*.kt")]
    if kotlin:
        rel = str(kotlin[0].relative_to(ROOT)).replace("\\", "/")
        assert rel in scanned, "the Android module is not guarded"


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
