"""
tests/test_version.py

Tests for src/utils/version.py (Fall 3.17 - in-app update check).

The comparison has to correctly order this project's actual version shapes:
pyproject.toml's PEP 440 style ("2.2.0.dev1") against GitHub's plain tag
style ("v2.2.0-beta"), plus a bare "vX.Y.Z" final release with no suffix.

Author: Bloodawn (KheivenD), 2026-09-22 (Fall 3.17).
"""

import sys
from pathlib import Path

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils.version import APP_VERSION, is_newer, parse_version  # noqa: E402


class TestParseVersion:
    def test_plain_semver(self):
        assert parse_version("2.2.0") == (2, 2, 0, 4, 0)

    def test_v_prefix_stripped(self):
        assert parse_version("v2.2.0") == parse_version("2.2.0")

    def test_pep440_dev(self):
        assert parse_version("2.2.0.dev1") == (2, 2, 0, 0, 1)

    def test_dash_beta(self):
        assert parse_version("2.2.0-beta") == (2, 2, 0, 2, 0)

    def test_dash_beta_with_number(self):
        assert parse_version("2.2.0-beta2") == (2, 2, 0, 2, 2)

    def test_compact_b(self):
        assert parse_version("2.2.0b1") == (2, 2, 0, 2, 1)

    def test_rc(self):
        assert parse_version("2.2.0rc1") == (2, 2, 0, 3, 1)

    def test_garbage_parses_to_zero(self):
        assert parse_version("not-a-version") == (0, 0, 0, 0, 0)

    def test_mobile_tag_still_parses_by_number(self):
        # is_newer's caller is responsible for filtering mobile- tags out by
        # prefix before comparing; parse_version itself just reads digits.
        assert parse_version("mobile-v0.9.0-beta") == (0, 0, 0, 0, 0)

    def test_empty_and_none_safe(self):
        assert parse_version("") == (0, 0, 0, 0, 0)
        assert parse_version(None) == (0, 0, 0, 0, 0)


class TestOrdering:
    def test_dev_is_less_than_beta_same_release(self):
        # This is the real case that matters: pyproject.toml currently says
        # "2.2.0.dev1" while the published GitHub tag is "v2.2.0-beta" - the
        # beta must count as newer even though the (major,minor,patch) tie.
        assert parse_version("v2.2.0-beta") > parse_version("2.2.0.dev1")

    def test_beta_is_less_than_final(self):
        assert parse_version("2.2.1") > parse_version("2.2.1-beta")

    def test_rc_is_between_beta_and_final(self):
        assert parse_version("2.2.0-beta") < parse_version("2.2.0rc1") < parse_version("2.2.0")

    def test_patch_beats_stage(self):
        assert parse_version("2.2.1.dev1") > parse_version("2.2.0")

    def test_minor_beats_patch(self):
        assert parse_version("2.3.0") > parse_version("2.2.99")

    def test_major_beats_everything(self):
        assert parse_version("3.0.0") > parse_version("2.99.99")


class TestIsNewer:
    def test_beta_release_is_newer_than_current_dev_build(self):
        assert is_newer("v2.2.0-beta", "2.2.0.dev1") is True

    def test_same_version_is_not_newer(self):
        assert is_newer("2.2.0.dev1", "2.2.0.dev1") is False

    def test_older_tag_is_not_newer(self):
        assert is_newer("v2.0.0-beta", "2.2.0.dev1") is False

    def test_defaults_to_comparing_against_app_version(self):
        # Whatever APP_VERSION currently is, something clearly ahead of it
        # (major version 999) must always read as newer, and the CURRENT
        # published tag must never accidentally be newer than itself.
        assert is_newer("v999.0.0") is True
        assert is_newer(APP_VERSION) is False

    def test_malformed_candidate_is_never_newer(self):
        assert is_newer("garbage", "2.2.0.dev1") is False
