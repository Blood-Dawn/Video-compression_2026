"""
src/utils/version.py

Single source of truth for the desktop app's OWN version number, plus the
comparison logic the in-app update check (planner TASK 3.17) needs.

Before this file, "2.2.0.dev1" was duplicated by hand in pyproject.toml and
installer/svcs.iss with nothing to catch the two drifting apart. This module
doesn't remove that duplication (svcs.iss is an Inno Setup script, not
Python, so it can't import this), but it gives the RUNNING APP one place to
read its own version from, and gives release day one clear rule: bump
APP_VERSION here, pyproject.toml's version, and svcs.iss's MyAppVersion
together (see docs/RELEASE-CHECKLIST.md).

Author: Bloodawn (KheivenD), 2026-09-22 (Fall 3.17 - in-app update check).
"""

from __future__ import annotations

import re
from typing import Optional

# Keep this in sync with pyproject.toml's [project].version and
# installer/svcs.iss's MyAppVersion. All three change together on release.
APP_VERSION = "2.2.0.dev1"

# Release-stage ordering for comparison purposes. Anything not recognized
# (including a fully final release, no suffix at all) ranks highest, so
# "2.2.0" beats "2.2.0.dev1", "2.2.0-beta", "2.2.0rc1", etc. - a plain
# version number is assumed to be the most-finished one.
_STAGE_RANK = {"dev": 0, "alpha": 1, "a": 1, "beta": 2, "b": 2, "rc": 3, "": 4}

# Matches "2.2.0", "v2.2.0", "2.2.0.dev1", "2.2.0-beta", "2.2.0-beta2",
# "2.2.0b1", "2.2.0rc1" - the handful of shapes this project's own version
# strings and GitHub release tags actually take (PEP 440 on the pyproject.toml
# side, a plain "vX.Y.Z[-stage]" on the GitHub tag side).
_VERSION_RE = re.compile(
    r"^[vV]?(\d+)\.(\d+)\.(\d+)(?:[.\-]?(dev|alpha|a|beta|b|rc)(\d*))?$"
)


def parse_version(raw: str) -> tuple[int, int, int, int, int]:
    """Parse a version string into a tuple that sorts correctly.

    Returns (major, minor, patch, stage_rank, stage_num). Anything this
    project's own versions/tags don't actually look like parses to
    (0, 0, 0, 0, 0) - the lowest possible value - rather than raising, so a
    malformed or unexpected tag from GitHub can never be mistaken for a
    newer release; it just gets silently ignored by the comparison.
    """
    m = _VERSION_RE.match((raw or "").strip())
    if not m:
        return (0, 0, 0, 0, 0)
    major, minor, patch, stage, num = m.groups()
    return (
        int(major),
        int(minor),
        int(patch),
        _STAGE_RANK.get(stage or "", 4),
        int(num) if num else 0,
    )


def is_newer(candidate: str, current: Optional[str] = None) -> bool:
    """True if `candidate` (e.g. a GitHub release tag) is a newer version
    than `current` (defaults to this build's own APP_VERSION)."""
    return parse_version(candidate) > parse_version(current or APP_VERSION)
