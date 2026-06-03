"""
tests/test_signing_step.py

Guards the wired-but-cert-gated Windows code-signing step (M5b TASK 5b.1).

The cert is the owner's to provide; this verifies the *step* is present and
safe: build.ps1 exposes -Sign, signs via signtool with a timestamp, reads the
cert from the environment (no secret in the repo), and degrades gracefully when
no cert is configured. The checklist and BLOCKERS record the gate.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 5b.1).
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent
BUILD = ROOT / "installer" / "build.ps1"
CHECKLIST = ROOT / "docs" / "RELEASE-CHECKLIST.md"
BLOCKERS = ROOT / "docs" / "BLOCKERS.md"


def test_build_has_sign_switch_and_signtool():
    body = BUILD.read_text(encoding="utf-8")
    assert "[switch]$Sign" in body
    assert "signtool" in body.lower()
    assert "Invoke-CodeSign" in body
    # SHA-256 + RFC3161 timestamp (not legacy SHA-1 only).
    assert "/fd" in body and "SHA256" in body and "/tr" in body


def test_signing_reads_cert_from_env_not_repo():
    body = BUILD.read_text(encoding="utf-8")
    assert "SVCS_SIGN_CERT" in body or "SVCS_SIGN_THUMBPRINT" in body
    assert "SVCS_SIGN_PASSWORD" in body


def test_signing_degrades_without_cert():
    body = BUILD.read_text(encoding="utf-8")
    # When no cert is set it must warn + skip, not hard-fail the build.
    assert "Skipping" in body


def test_signs_both_bundle_and_installer():
    body = BUILD.read_text(encoding="utf-8")
    # Two Invoke-CodeSign call sites: the bundle exe and the installer exe.
    assert body.count("Invoke-CodeSign -FilePath") >= 2


def test_checklist_and_blockers_cover_signing():
    cl = CHECKLIST.read_text(encoding="utf-8").lower()
    assert "signtool" in cl and "-sign" in cl
    bl = BLOCKERS.read_text(encoding="utf-8").lower()
    assert "signing step wired" in bl or "signing step" in bl
    assert "signpath" in bl  # the free-OSS-cert lead is recorded
