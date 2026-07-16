"""
tests/test_version_consistency.py

Guards the project version (R2.0). The dashboard release is 2.1.0; the installer
name is driven by installer/svcs.iss MyAppVersion. This pins both to the same
value so a future bump cannot leave them out of sync, and pins the beta tag in
the release docs.

Author: Bloodawn (KheivenD), 2026-06-03 (R2.0 - version bump).
"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent
EXPECTED = "2.2.0.dev0"


def _pyproject_version():
    data = tomllib.load((ROOT / "pyproject.toml").open("rb"))
    return data["project"]["version"]


def _iss_version():
    text = (ROOT / "installer" / "svcs.iss").read_text(encoding="utf-8")
    m = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', text)
    assert m, "MyAppVersion not found in svcs.iss"
    return m.group(1)


def test_pyproject_version_is_expected():
    assert _pyproject_version() == EXPECTED


def test_installer_version_matches_pyproject():
    assert _iss_version() == _pyproject_version()


def test_release_docs_use_beta_tag():
    checklist = (ROOT / "docs" / "RELEASE-CHECKLIST.md").read_text(encoding="utf-8")
    assert "v2.1.0-beta" in checklist
    assert (ROOT / "docs" / "release-notes-v2.1.0-beta.md").is_file()
