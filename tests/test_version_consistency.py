"""
tests/test_version_consistency.py

Guards the project version (R2.0). The dashboard release is 2.1.0; the installer
name is driven by installer/svcs.iss MyAppVersion. This pins both to the same
value so a future bump cannot leave them out of sync, and pins the beta tag in
the release docs.

2026-09-24: added src/utils/version.py's APP_VERSION to the pinned set (it
was missing - the file's own docstring says three files stay in sync but
this test only ever checked two) and a tripwire against the exact bug this
found: a release's own baked-in version string was left at a "dev" stage
that could never numerically catch up to that release's own "beta"-stage
GitHub tag, so /api/setup/update_check reported "update available" forever,
even immediately after installing that exact release. See version.py's
APP_VERSION comment for the full story.

Author: Bloodawn (KheivenD), 2026-06-03 (R2.0 - version bump).
"""

import re
import tomllib
from pathlib import Path

from utils.version import APP_VERSION, is_newer

ROOT = Path(__file__).parent.parent
EXPECTED = "2.2.1.dev0"

# The last tag this project actually published for the desktop app. Update
# this the moment a newer desktop tag ships - if you forget, this test
# starts failing instead of silently letting APP_VERSION fall behind it
# again, which is exactly how the update-check nag bug happened.
_LAST_PUBLISHED_DESKTOP_TAG = "v2.2.0-beta"


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


def test_app_version_matches_pyproject():
    """The third of the three files version.py's own docstring says must
    stay in sync - not checked here until 2026-09-24, which is how it was
    able to drift without any test catching it."""
    assert APP_VERSION == _pyproject_version()


def test_dev_version_is_never_behind_the_last_published_release():
    """Tripwire for the update-check perpetual-nag bug: the running dev
    build must always be reported as newer than (or equal to) the last
    tag this project actually shipped for the desktop app. If this fails,
    it means APP_VERSION/pyproject.toml/svcs.iss were left at the same
    number as a release that has since been tagged - bump them to the
    NEXT version in dev stage (e.g. 2.2.0-beta shipped -> move to
    2.2.1.dev0), then update _LAST_PUBLISHED_DESKTOP_TAG above once the
    next desktop tag actually goes out.
    """
    assert is_newer(_LAST_PUBLISHED_DESKTOP_TAG, APP_VERSION) is False


def test_release_docs_use_beta_tag():
    checklist = (ROOT / "docs" / "RELEASE-CHECKLIST.md").read_text(encoding="utf-8")
    assert "v2.2.0-beta" in checklist
    assert (ROOT / "docs" / "releases" / "release-notes-v2.2.0-beta.md").is_file()
