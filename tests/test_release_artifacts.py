"""
tests/test_release_artifacts.py

Guards the release-prep artifacts for the public beta (M5 TASK 5.4).

The actual tag + publish is a gated, owner-only step; this just verifies the
non-gated prep the agent produced is present and coherent: a repeatable release
checklist that defers publishing to the owner, draft release notes that are
honest about the unsigned beta, and the BLOCKERS entry recording the gate.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 5.4).
"""

from pathlib import Path

import pytest

DOCS = Path(__file__).parent.parent / "docs"
CHECKLIST = DOCS / "RELEASE-CHECKLIST.md"
NOTES = DOCS / "release-notes-v2.1.0-beta.md"
BLOCKERS = DOCS / "BLOCKERS.md"


def test_checklist_exists_and_is_repeatable():
    body = CHECKLIST.read_text(encoding="utf-8").lower()
    for step in ("run_tests", "build", "smoke", "checksum", "sha256", "draft"):
        assert step in body, f"checklist missing the {step!r} step"


def test_checklist_defers_publish_to_owner():
    body = CHECKLIST.read_text(encoding="utf-8").lower()
    assert "owner" in body
    # publishing/tagging is explicitly the owner's action (gated)
    assert "publish" in body and "tag" in body


def test_release_notes_exist_and_flag_unsigned_beta():
    body = NOTES.read_text(encoding="utf-8").lower()
    assert "unsigned" in body
    assert "beta" in body
    assert "smartscreen" in body
    # verification guidance for users
    assert "sha256" in body
    # license is stated
    assert "agpl" in body


def test_blockers_records_the_publish_gate():
    body = BLOCKERS.read_text(encoding="utf-8").lower()
    assert "v2.1.0-beta" in body
    assert "owner" in body
    assert "release-checklist" in body
